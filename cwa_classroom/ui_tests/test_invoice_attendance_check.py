"""Tests for the attendance-completeness gate on the Generate Invoices form.

The gate must only block when billing actually depends on attendance — i.e.
when ``billing_type != 'upfront'`` AND ``attendance_mode == 'attended_only'``.
For the default "All Class Days" mode (and for upfront billing) missing
attendance marks must NOT block invoice generation.

Also regression-tests the warning panel render: each row must show the
session classroom name, date, and start time (the panel previously rendered
empty parentheses because the template iterated dicts as if they were
``ClassSession`` instances).
"""

from datetime import date, time, timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.invoice


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _go_generate(page, url):
    page.goto(f"{url}/invoicing/generate/")
    page.wait_for_load_state("domcontentloaded")


def _backdate_enrollment(classroom, student, days_ago: int = 30):
    """Force ``joined_at`` to be older than a session in the past.

    ``ClassStudent.joined_at`` uses ``auto_now_add`` so a freshly-created
    enrolment defaults to "now". The validator filters by
    ``joined_at__date__lte=session.date`` — without this back-date, a session
    dated even one day ago would not see the student as enrolled and the
    "missing attendance" check would silently report nothing.
    """
    from classroom.models import ClassStudent

    ClassStudent.objects.filter(
        classroom=classroom, student=student,
    ).update(joined_at=timezone.now() - timedelta(days=days_ago))


def _fill_custom_period(page, start: date, end: date):
    page.locator("#period-custom").click()
    page.locator("#billing_period_start").fill(start.isoformat())
    page.locator("#billing_period_end").fill(end.isoformat())
    page.locator("#billing_period_end").dispatch_event("change")


def _select_billing_type(page, value: str):
    """value: ``post_term`` or ``upfront``."""
    page.locator(f"input[name='billing_type'][value='{value}']").check()


def _select_attendance_mode(page, value: str):
    """value: ``all_class_days`` or ``attended_only``."""
    page.locator(f"input[name='attendance_mode'][value='{value}']").check()


def _submit(page):
    page.get_by_role("button", name="Generate Invoices").click()
    page.wait_for_load_state("domcontentloaded")


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unmarked_session(db, classroom, teacher_user, enrolled_student):
    """A completed past session with no ``StudentAttendance`` for the enrolled student."""
    from attendance.models import ClassSession

    _backdate_enrollment(classroom, enrolled_student)
    return ClassSession.objects.create(
        classroom=classroom,
        date=date.today() - timedelta(days=7),
        start_time=time(14, 30),
        end_time=time(15, 30),
        status="completed",
        created_by=teacher_user,
    )


@pytest.fixture
def fully_marked_session(db, classroom, teacher_user, enrolled_student):
    """A completed past session with attendance marked for every enrolled student."""
    from attendance.models import ClassSession, StudentAttendance

    _backdate_enrollment(classroom, enrolled_student)
    sess = ClassSession.objects.create(
        classroom=classroom,
        date=date.today() - timedelta(days=5),
        start_time=time(11, 15),
        end_time=time(12, 15),
        status="completed",
        created_by=teacher_user,
    )
    StudentAttendance.objects.create(
        session=sess,
        student=enrolled_student,
        status="present",
    )
    return sess


# ===========================================================================
# 1. Default "All Class Days" mode skips the attendance check
# ===========================================================================

class TestAllClassDaysSkipsAttendanceCheck:
    """When billing charges every held session, missing attendance must not block."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, unmarked_session):
        self.url = live_server.url
        self.page = page
        self.session = unmarked_session
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_no_warning_panel_with_all_class_days(self):
        """Default 'All Class Days' + unmarked attendance → no warning panel."""
        _fill_custom_period(
            self.page,
            self.session.date - timedelta(days=1),
            self.session.date + timedelta(days=1),
        )
        _select_billing_type(self.page, "post_term")
        _select_attendance_mode(self.page, "all_class_days")
        _submit(self.page)

        expect(self.page.get_by_text("Attendance Not Complete")).to_have_count(0)


# ===========================================================================
# 2. "Attended Only" mode blocks when attendance is missing
# ===========================================================================

class TestAttendedOnlyBlocksOnUnmarked:
    """Attended-only billing must surface unmarked sessions before invoicing."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, unmarked_session):
        self.url = live_server.url
        self.page = page
        self.session = unmarked_session
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)
        _fill_custom_period(
            self.page,
            self.session.date - timedelta(days=1),
            self.session.date + timedelta(days=1),
        )
        _select_billing_type(self.page, "post_term")
        _select_attendance_mode(self.page, "attended_only")
        _submit(self.page)

    def test_warning_panel_visible(self):
        expect(self.page.get_by_text("Attendance Not Complete")).to_be_visible()

    def test_unmarked_row_shows_classroom_name(self):
        row = self.page.locator("li", has_text=self.session.classroom.name)
        expect(row).to_have_count(1)

    def test_unmarked_row_shows_session_date(self):
        """Regression: dict-vs-instance template bug would render an empty date."""
        expected_date = self.session.date.strftime("%b. %d, %Y").lstrip("0").replace(" 0", " ")
        # Django's "M d, Y" filter outputs e.g. "Apr 20, 2026" — be lenient on the day prefix
        row = self.page.locator("li", has_text=self.session.classroom.name)
        # Year + month always present
        expect(row).to_contain_text(str(self.session.date.year))
        expect(row).to_contain_text(self.session.date.strftime("%b"))
        expect(row).to_contain_text(str(self.session.date.day))

    def test_unmarked_row_shows_session_time(self):
        """Regression: empty parentheses meant start_time was missing."""
        row = self.page.locator("li", has_text=self.session.classroom.name)
        expect(row).to_contain_text("14:30")

    def test_unmarked_row_has_no_empty_parens(self):
        """Regression: bug rendered '— ()' with no date or time inside."""
        row = self.page.locator("li", has_text=self.session.classroom.name)
        text = row.inner_text()
        assert "()" not in text, f"Empty parentheses still in row: {text!r}"


# ===========================================================================
# 3. "Attended Only" passes through cleanly when all attendance is marked
# ===========================================================================

class TestAttendedOnlyPassesWhenAllMarked:
    """attended_only + every student marked → no warning panel."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, fully_marked_session):
        self.url = live_server.url
        self.page = page
        self.session = fully_marked_session
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_no_warning_when_all_marked(self):
        _fill_custom_period(
            self.page,
            self.session.date - timedelta(days=1),
            self.session.date + timedelta(days=1),
        )
        _select_billing_type(self.page, "post_term")
        _select_attendance_mode(self.page, "attended_only")
        _submit(self.page)

        expect(self.page.get_by_text("Attendance Not Complete")).to_have_count(0)


# ===========================================================================
# 4. Upfront billing skips the attendance check entirely
# ===========================================================================

class TestUpfrontSkipsAttendanceCheck:
    """Upfront billing never validates attendance — unmarked sessions are irrelevant."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, unmarked_session):
        self.url = live_server.url
        self.page = page
        self.session = unmarked_session
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_no_warning_with_upfront_on_past_period(self):
        """Past-period + upfront + unmarked attendance → no warning panel."""
        _fill_custom_period(
            self.page,
            self.session.date - timedelta(days=1),
            self.session.date + timedelta(days=1),
        )
        # Even if the user picked "attended_only" beforehand, switching to
        # upfront should make the validator skip — we explicitly leave it set
        # to attended_only to prove the upfront branch wins.
        _select_attendance_mode(self.page, "attended_only")
        _select_billing_type(self.page, "upfront")
        _submit(self.page)

        expect(self.page.get_by_text("Attendance Not Complete")).to_have_count(0)


# ===========================================================================
# 5. Form-data round-trip when validation fails
# ===========================================================================

class TestWarningPanelPreservesFormData:
    """When the warning re-renders the form, the user's choices must be remembered."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, unmarked_session):
        self.url = live_server.url
        self.page = page
        self.session = unmarked_session
        self.start = self.session.date - timedelta(days=1)
        self.end = self.session.date + timedelta(days=1)
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)
        _fill_custom_period(self.page, self.start, self.end)
        _select_billing_type(self.page, "post_term")
        _select_attendance_mode(self.page, "attended_only")
        _submit(self.page)

    def test_billing_period_start_preserved(self):
        expect(self.page.locator("#billing_period_start")).to_have_value(self.start.isoformat())

    def test_billing_period_end_preserved(self):
        expect(self.page.locator("#billing_period_end")).to_have_value(self.end.isoformat())

    def test_attended_only_radio_still_checked(self):
        radio = self.page.locator("input[name='attendance_mode'][value='attended_only']")
        expect(radio).to_be_checked()
