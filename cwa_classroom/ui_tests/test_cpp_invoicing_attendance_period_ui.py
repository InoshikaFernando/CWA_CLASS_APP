"""
UI automation tests — invoice attendance-scope fix + period filter feature.

Test 1 — Period date-range filter (invoice list page):
  - Period From / Period To inputs visible
  - Filtering by date range shows only matching invoices
  - Selected dates persist in inputs after filter submit
  - Clear link resets the filter

Test 2 — Attendance scope fix (generate invoices page):
  - Generating for a classroom with all attendance marked proceeds without error
  - Generating for a classroom with unmarked attendance shows the error banner
  - Scratch 01 unmarked sessions do NOT block Scratch 06 invoice generation

Note: all invoicing views require Role.INSTITUTE_OWNER / HEAD_OF_INSTITUTE / ACCOUNTANT.
Tests use hoi_user (Role.INSTITUTE_OWNER) + hoi_school_setup to satisfy this.
"""

from __future__ import annotations

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from playwright.sync_api import expect

from .conftest import do_login, _assign_role, TEST_PASSWORD, _RUN_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invoice(school, student, number, period_start, period_end):
    """Create a minimal issued invoice (created_by is nullable, omitted)."""
    from classroom.models import Invoice
    return Invoice.objects.create(
        invoice_number=number,
        school=school,
        student=student,
        billing_period_start=period_start,
        billing_period_end=period_end,
        attendance_mode="all_class_days",
        calculated_amount=Decimal("100.00"),
        amount=Decimal("100.00"),
        status="issued",
    )


def _make_student(school, suffix):
    """Create a user with Role.STUDENT and enrol them in the school."""
    from accounts.models import CustomUser, Role
    from classroom.models import SchoolStudent

    user = CustomUser.objects.create_user(
        username=f"inv_stu_{suffix}_{_RUN_ID}",
        password=TEST_PASSWORD,
        email=f"inv_stu_{suffix}_{_RUN_ID}@test.local",
        first_name=f"Stu{suffix}",
        last_name="Invoicing",
        profile_completed=True,
        must_change_password=False,
    )
    _assign_role(user, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=user, is_active=True)
    return user


def _make_classroom(school, department, name):
    """Create an active classroom in the given department."""
    from classroom.models import ClassRoom
    return ClassRoom.objects.create(
        name=name,
        school=school,
        department=department,
        day="wednesday",
        start_time="18:00",
        end_time="19:00",
        is_active=True,
    )


def _enrol(classroom, student):
    """Enrol student in classroom, backdated to Jan 2025 to pre-date all sessions."""
    from classroom.models import ClassStudent
    cs = ClassStudent.objects.create(
        classroom=classroom, student=student, is_active=True,
    )
    ClassStudent.objects.filter(pk=cs.pk).update(
        joined_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    return cs


def _make_session(classroom, session_date, status="completed"):
    from classroom.models import ClassSession
    return ClassSession.objects.create(
        classroom=classroom,
        date=session_date,
        status=status,
        start_time="18:00",
        end_time="19:00",
    )


def _mark_present(session, student):
    from classroom.models import StudentAttendance
    StudentAttendance.objects.get_or_create(
        session=session, student=student,
        defaults={"status": "present"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def invoicing_school_setup(db, school, department, hoi_user, hoi_school_setup):
    """
    Two issued invoices in different billing periods, accessible via hoi_user.

      INV-UI-MAY  — billing period May 2026
      INV-UI-AUG  — billing period August 2026

    hoi_school_setup attaches hoi_user to the school so the invoicing views
    return the correct school for that user.
    """
    student_may = _make_student(school, "may")
    student_aug = _make_student(school, "aug")

    inv_may = _make_invoice(
        school, student_may,
        f"INV-UI-MAY-{_RUN_ID}",
        date(2026, 5, 1), date(2026, 5, 31),
    )
    inv_aug = _make_invoice(
        school, student_aug,
        f"INV-UI-AUG-{_RUN_ID}",
        date(2026, 8, 1), date(2026, 8, 31),
    )
    return {
        "school": school,
        "owner": hoi_user,
        "inv_may": inv_may,
        "inv_aug": inv_aug,
    }


@pytest.fixture
def attendance_scope_setup(db, school, department, hoi_user, hoi_school_setup):
    """
    Two classrooms with contrasting attendance state in May 2025:

      scratch01 — completed session with NO attendance (triggers the bug)
      scratch06 — completed session with attendance fully marked

    hoi_school_setup attaches hoi_user so invoicing views work.
    """
    scratch01 = _make_classroom(school, department, f"Scratch 01 UI {_RUN_ID}")
    scratch06 = _make_classroom(school, department, f"Scratch 06 UI {_RUN_ID}")

    student01 = _make_student(school, "s01ui")
    student06 = _make_student(school, "s06ui")

    _enrol(scratch01, student01)
    _enrol(scratch06, student06)

    session_date = date(2025, 5, 6)

    # Scratch 01: completed session — intentionally NO attendance recorded
    _make_session(scratch01, session_date)

    # Scratch 06: completed session — attendance fully marked
    sess06 = _make_session(scratch06, session_date)
    _mark_present(sess06, student06)

    return {
        "school": school,
        "owner": hoi_user,
        "scratch01": scratch01,
        "scratch06": scratch06,
    }


# ===========================================================================
# Test class 1 — Period filter on invoice list
# ===========================================================================

class TestInvoicePeriodFilter:
    """UI tests for the Period From / Period To filter on /invoicing/."""

    def test_period_filter_inputs_visible(
        self, live_server, page, invoicing_school_setup,
    ):
        """Period From and Period To inputs are rendered on the invoice list page."""
        data = invoicing_school_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator("input[name='period_start']")).to_be_visible()
        expect(page.locator("input[name='period_end']")).to_be_visible()
        expect(page.get_by_text("Period From")).to_be_visible()
        expect(page.get_by_text("Period To")).to_be_visible()

    def test_period_start_filter_shows_only_august(
        self, live_server, page, invoicing_school_setup,
    ):
        """Period From = 2026-07-01 shows August invoice, hides May invoice."""
        data = invoicing_school_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        inv_may_num = data["inv_may"].invoice_number
        inv_aug_num = data["inv_aug"].invoice_number

        page.goto(f"{url}/invoicing/?period_start=2026-07-01")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text(inv_aug_num)).to_be_visible()
        expect(page.get_by_text(inv_may_num)).not_to_be_visible()

    def test_period_end_filter_shows_only_may(
        self, live_server, page, invoicing_school_setup,
    ):
        """Period To = 2026-06-30 shows May invoice, hides August invoice."""
        data = invoicing_school_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        inv_may_num = data["inv_may"].invoice_number
        inv_aug_num = data["inv_aug"].invoice_number

        page.goto(f"{url}/invoicing/?period_end=2026-06-30")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text(inv_may_num)).to_be_visible()
        expect(page.get_by_text(inv_aug_num)).not_to_be_visible()

    def test_period_dates_persist_after_filter_submit(
        self, live_server, page, invoicing_school_setup,
    ):
        """After clicking Filter the Period From/To values stay in the inputs (JS repopulates from URL)."""
        data = invoicing_school_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/")
        page.wait_for_load_state("domcontentloaded")

        # Set date inputs via JS (avoids locale-dependent fill() behaviour on type=date)
        page.evaluate("document.querySelector('input[name=\"period_start\"]').value = '2026-05-01'")
        page.evaluate("document.querySelector('input[name=\"period_end\"]').value = '2026-05-31'")

        page.get_by_role("button", name="Filter").click()
        page.wait_for_load_state("domcontentloaded")

        # After reload the {% block extra_js %} snippet repopulates inputs from URLSearchParams
        period_start_val = page.locator("input[name='period_start']").input_value()
        period_end_val = page.locator("input[name='period_end']").input_value()

        assert period_start_val == "2026-05-01", f"Expected 2026-05-01, got {period_start_val!r}"
        assert period_end_val == "2026-05-31", f"Expected 2026-05-31, got {period_end_val!r}"

    def test_clear_link_resets_period_filter(
        self, live_server, page, invoicing_school_setup,
    ):
        """Clear link appears when period filter is active and removes the filter."""
        data = invoicing_school_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/?period_start=2026-05-01")
        page.wait_for_load_state("domcontentloaded")

        clear_link = page.get_by_role("link", name="Clear")
        expect(clear_link).to_be_visible()
        clear_link.click()
        page.wait_for_load_state("domcontentloaded")

        # After clearing both invoices should be visible
        inv_may_num = data["inv_may"].invoice_number
        inv_aug_num = data["inv_aug"].invoice_number
        expect(page.get_by_text(inv_may_num)).to_be_visible()
        expect(page.get_by_text(inv_aug_num)).to_be_visible()

        # Period filter inputs should be empty
        assert page.locator("input[name='period_start']").input_value() == ""

    def test_no_match_shows_empty_state(
        self, live_server, page, invoicing_school_setup,
    ):
        """A period with no invoices shows the 'No Invoices Found' empty state."""
        data = invoicing_school_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/?period_start=2020-01-01&period_end=2020-12-31")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("No Invoices Found")).to_be_visible()


# ===========================================================================
# Test class 2 — Attendance scope fix (generate invoices page)
# ===========================================================================

class TestAttendanceScopeUI:
    """
    UI tests verifying the classroom-scoped attendance check.

    Bug: generating invoices for Scratch 06 was blocked because Scratch 01 had
    unmarked attendance in the same period — even though Scratch 01 was not the
    selected classroom.

    Fix: attendance check is scoped to the selected classroom only.
    """

    # ------------------------------------------------------------------
    # Helpers shared between tests
    # ------------------------------------------------------------------

    @staticmethod
    def _select_custom_period(page, start_iso, end_iso):
        """Click the Custom period card, wait for date inputs to appear, fill them."""
        page.locator("#period-custom").click()
        page.wait_for_selector("#custom-date-section:not([style*='display: none'])", timeout=5_000)
        page.evaluate(
            f"document.getElementById('billing_period_start').value = '{start_iso}'"
        )
        page.evaluate(
            f"document.getElementById('billing_period_end').value = '{end_iso}'"
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_attendance_error_banner_visible_when_unmarked_no_classroom(
        self, live_server, page, attendance_scope_setup,
    ):
        """
        No classroom selected → school-wide check → Scratch 01's unmarked
        sessions trigger the 'Attendance Not Complete' error banner.
        """
        data = attendance_scope_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/generate/")
        page.wait_for_load_state("domcontentloaded")

        self._select_custom_period(page, "2025-05-01", "2025-05-31")

        # Post-Term is the default; set Attended Only to trigger attendance check
        page.locator("input[name='attendance_mode'][value='attended_only']").check()

        # Leave classroom as default ("All Classes") — school-wide check
        page.get_by_role("button", name="Generate Invoices").click()
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("Attendance Not Complete")).to_be_visible()
        # Scope to the unmarked-sessions list item — the classroom name also now
        # appears in the (preserved) class dropdown, so a bare get_by_text would
        # match 2 elements.
        expect(page.locator("li", has_text=data["scratch01"].name).first).to_be_visible()

    def test_scratch06_not_blocked_by_scratch01_unmarked(
        self, live_server, page, attendance_scope_setup,
    ):
        """
        Key regression test: selecting Scratch 06 must NOT trigger the attendance
        error even though Scratch 01 has unmarked sessions in the same billing
        period. The fix scopes the check to the selected classroom only.
        """
        data = attendance_scope_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/generate/")
        page.wait_for_load_state("domcontentloaded")

        self._select_custom_period(page, "2025-05-01", "2025-05-31")
        page.locator("input[name='attendance_mode'][value='attended_only']").check()

        # Select Scratch 06 — all attendance marked, should not be blocked
        page.locator("#scope-class").select_option(label=data["scratch06"].name)

        page.get_by_role("button", name="Generate Invoices").click()
        page.wait_for_load_state("domcontentloaded")

        # The attendance error must NOT appear
        expect(page.get_by_text("Attendance Not Complete")).not_to_be_visible()

    def test_scratch01_selected_shows_its_own_error(
        self, live_server, page, attendance_scope_setup,
    ):
        """
        Selecting Scratch 01 (the class with unmarked attendance) correctly shows
        the error banner — confirming the check still works for the right classroom.
        """
        data = attendance_scope_setup
        url = live_server.url
        do_login(page, url, data["owner"])

        page.goto(f"{url}/invoicing/generate/")
        page.wait_for_load_state("domcontentloaded")

        self._select_custom_period(page, "2025-05-01", "2025-05-31")
        page.locator("input[name='attendance_mode'][value='attended_only']").check()

        # Select Scratch 01 — has unmarked sessions
        page.locator("#scope-class").select_option(label=data["scratch01"].name)

        page.get_by_role("button", name="Generate Invoices").click()
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("Attendance Not Complete")).to_be_visible()
        # Scope to the unmarked-sessions list item — the classroom name also now
        # appears in the (preserved) class dropdown, so a bare get_by_text would
        # match 2 elements.
        expect(page.locator("li", has_text=data["scratch01"].name).first).to_be_visible()
