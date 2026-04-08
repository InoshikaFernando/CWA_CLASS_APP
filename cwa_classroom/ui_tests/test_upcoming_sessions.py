"""UI tests for upcoming sessions display across all user dashboards.

Rules verified:
- Only sessions with an actual ClassSession record are shown (no schedule fallback).
- Sessions that fall on a SchoolHoliday or PublicHoliday are excluded.
- The section title includes 'Upcoming' / 'Upcoming Classes'.
"""

from __future__ import annotations

import pytest
from datetime import date, time, timedelta

from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.dashboard


# ---------------------------------------------------------------------------
# Shared holiday fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def school_holiday(db, school):
    """A school holiday covering today+5 to today+7."""
    from classroom.models import SchoolHoliday

    holiday_date = date.today() + timedelta(days=5)
    return SchoolHoliday.objects.create(
        school=school,
        name="Half-Term Break",
        start_date=holiday_date,
        end_date=holiday_date + timedelta(days=2),
    )


@pytest.fixture
def public_holiday(db, school):
    """A public holiday on today+4."""
    from classroom.models import PublicHoliday

    return PublicHoliday.objects.create(
        school=school,
        name="Bank Holiday",
        date=date.today() + timedelta(days=4),
    )


@pytest.fixture
def session_on_school_holiday(db, classroom, teacher_user, school_holiday):
    """A scheduled session whose date falls inside a school holiday."""
    from attendance.models import ClassSession

    return ClassSession.objects.create(
        classroom=classroom,
        date=school_holiday.start_date,
        start_time=time(9, 0),
        end_time=time(10, 0),
        status="scheduled",
        created_by=teacher_user,
    )


@pytest.fixture
def session_on_public_holiday(db, classroom, teacher_user, public_holiday):
    """A scheduled session whose date falls on a public holiday."""
    from attendance.models import ClassSession

    return ClassSession.objects.create(
        classroom=classroom,
        date=public_holiday.date,
        start_time=time(9, 0),
        end_time=time(10, 0),
        status="scheduled",
        created_by=teacher_user,
    )


@pytest.fixture
def normal_future_session(db, classroom, teacher_user):
    """A scheduled session on a non-holiday day (today+2)."""
    from attendance.models import ClassSession

    return ClassSession.objects.create(
        classroom=classroom,
        date=date.today() + timedelta(days=2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        status="scheduled",
        created_by=teacher_user,
    )


# ---------------------------------------------------------------------------
# Student hub
# ---------------------------------------------------------------------------

class TestStudentUpcomingSessions:
    """Student hub /hub/ shows upcoming sessions; holiday sessions are excluded."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, timelog):
        self.url = live_server.url
        self.page = page
        self.user = enrolled_student

    def _go(self):
        do_login(self.page, self.url, self.user)
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")

    def test_upcoming_classes_label_present(self, normal_future_session):
        """Mini-card is labelled 'Upcoming Classes'."""
        self._go()
        assert_page_has_text(self.page, "Upcoming")

    def test_normal_session_shown(self, normal_future_session):
        """A non-holiday session causes the class name to appear in the upcoming card."""
        self._go()
        # The amber mini-card shows the first upcoming session's classroom name
        assert_page_has_text(self.page, "Year 7 Maths")

    def test_session_on_school_holiday_shows_free(self, session_on_school_holiday):
        """When the only upcoming session is on a school holiday, the card shows 'Free!'."""
        self._go()
        # Holiday session excluded → upcoming_classes is empty → "Free! 🎉" shown
        assert_page_has_text(self.page, "Free!")

    def test_session_on_public_holiday_shows_free(self, session_on_public_holiday):
        """When the only upcoming session is on a public holiday, the card shows 'Free!'."""
        self._go()
        assert_page_has_text(self.page, "Free!")

    def test_holiday_session_excluded_normal_session_shown(
        self, normal_future_session, session_on_school_holiday
    ):
        """Normal session (today+2) shown; school holiday session (today+5) not in card."""
        self._go()
        # The upcoming card shows the first session: the normal one at today+2
        assert_page_has_text(self.page, "Year 7 Maths")
        # Card should NOT show Free! since there is a valid upcoming session
        body = self.page.locator("body").inner_text()
        assert "Free!" not in body


# ---------------------------------------------------------------------------
# Teacher dashboard
# ---------------------------------------------------------------------------

class TestTeacherUpcomingSessions:
    """Teacher dashboard /teacher/ shows upcoming sessions; holiday sessions excluded."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, department, classroom):
        self.url = live_server.url
        self.page = page
        self.user = teacher_user

    def _go(self):
        do_login(self.page, self.url, self.user)
        self.page.goto(f"{self.url}/teacher/")
        self.page.wait_for_load_state("domcontentloaded")

    def test_upcoming_sessions_label_present(self, normal_future_session):
        """Teacher dashboard has a visible 'Upcoming Sessions' heading."""
        self._go()
        assert_page_has_text(self.page, "Upcoming Sessions")

    def test_normal_session_shown(self, normal_future_session):
        """A non-holiday session appears in the teacher upcoming sessions list."""
        self._go()
        assert_page_has_text(self.page, "Year 7 Maths")

    def test_session_on_school_holiday_shows_no_upcoming(self, session_on_school_holiday):
        """When the only session is on a school holiday, 'No upcoming sessions.' is shown."""
        self._go()
        assert_page_has_text(self.page, "No upcoming sessions.")

    def test_session_on_public_holiday_shows_no_upcoming(self, session_on_public_holiday):
        """When the only session is on a public holiday, 'No upcoming sessions.' is shown."""
        self._go()
        assert_page_has_text(self.page, "No upcoming sessions.")

    def test_holiday_excluded_normal_shown(
        self, normal_future_session, session_on_school_holiday
    ):
        """Normal session visible; 'No upcoming sessions.' is NOT shown."""
        self._go()
        assert_page_has_text(self.page, "Year 7 Maths")
        body = self.page.locator("body").inner_text()
        assert "No upcoming sessions." not in body


# ---------------------------------------------------------------------------
# HoD dashboard  (HoD user is also made a ClassTeacher so the section renders)
# ---------------------------------------------------------------------------

@pytest.fixture
def hod_as_teacher(db, hod_user, classroom):
    """Add HoD user as a ClassTeacher so the upcoming sessions section is rendered."""
    from classroom.models import ClassTeacher

    ClassTeacher.objects.get_or_create(classroom=classroom, teacher=hod_user)
    return hod_user


class TestHoDUpcomingSessions:
    """HoD /dashboard/ shows upcoming sessions; holiday sessions excluded."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hod_as_teacher, school, department, classroom):
        self.url = live_server.url
        self.page = page
        self.user = hod_as_teacher

    def _go(self):
        do_login(self.page, self.url, self.user)
        self.page.goto(f"{self.url}/dashboard/")
        self.page.wait_for_load_state("domcontentloaded")

    def test_upcoming_label_present(self, normal_future_session):
        """HoD dashboard renders an 'Upcoming Classes' / 'My Next Classes' section."""
        self._go()
        body = self.page.locator("body").inner_text()
        assert "Next Classes" in body or "Upcoming Classes" in body

    def test_normal_session_shown(self, normal_future_session):
        """A non-holiday session appears on the HoD upcoming sessions section."""
        self._go()
        # The upcoming sessions section should show the class name
        upcoming = self.page.locator("text=Year 7 Maths")
        expect(upcoming.first).to_be_visible()

    def test_session_on_school_holiday_section_empty(self, session_on_school_holiday):
        """When only a school holiday session exists, the upcoming section is hidden."""
        self._go()
        # With only a holiday session, upcoming_sessions is empty,
        # so the {% if upcoming_sessions or next_classes_from_schedule %} block hides the section.
        body = self.page.locator("body").inner_text()
        assert "My Next Classes" not in body and "Upcoming Classes" not in body

    def test_session_on_public_holiday_section_empty(self, session_on_public_holiday):
        """When only a public holiday session exists, the upcoming section is hidden."""
        self._go()
        body = self.page.locator("body").inner_text()
        assert "My Next Classes" not in body and "Upcoming Classes" not in body

    def test_holiday_excluded_normal_shown(
        self, normal_future_session, session_on_school_holiday
    ):
        """Normal session visible; section heading present."""
        self._go()
        body = self.page.locator("body").inner_text()
        assert "Next Classes" in body or "Upcoming Classes" in body
        expect(self.page.locator("text=Year 7 Maths").first).to_be_visible()
