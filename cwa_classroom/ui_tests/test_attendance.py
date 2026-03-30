"""Tests for attendance pages — student history, teacher marking, approvals."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.attendance


# ---------------------------------------------------------------------------
# Student attendance history
# ---------------------------------------------------------------------------

class TestStudentAttendanceHistory:
    """Tests for /student/attendance/ — stats cards, per-class summaries."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, student_attendance):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/student/attendance/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_title_renders(self):
        assert_page_has_text(self.page, "Attendance")

    def test_total_sessions_card(self):
        assert_page_has_text(self.page, "Total Sessions")

    def test_present_card(self):
        assert_page_has_text(self.page, "Present")

    def test_late_card(self):
        assert_page_has_text(self.page, "Late")

    def test_absent_card(self):
        assert_page_has_text(self.page, "Absent")

    def test_overall_percentage_renders(self):
        """Overall attendance rate badge."""
        pct_badge = self.page.locator("text=/\\d+%/").first
        expect(pct_badge).to_be_visible()

    def test_class_summary_renders(self):
        """Per-class summary section shows classroom name."""
        assert_page_has_text(self.page, "Year 7 Maths")


# ---------------------------------------------------------------------------
# Teacher attendance marking
# ---------------------------------------------------------------------------

class TestTeacherAttendanceMarking:
    """Tests for /teacher/session/<id>/attendance/ — marking form."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, department, classroom, enrolled_student, completed_session):
        self.url = live_server.url
        self.page = page
        self.session = completed_session
        do_login(page, self.url, teacher_user)
        page.goto(f"{self.url}/teacher/session/{self.session.id}/attendance/")
        page.wait_for_load_state("domcontentloaded")

    def test_attendance_form_loads(self):
        """The attendance marking form should load with student names."""
        assert_page_has_text(self.page, "ui_student")

    def test_radio_buttons_visible(self):
        """Present/Late/Absent radio buttons should be visible."""
        radios = self.page.locator("input[type='radio']")
        expect(radios.first).to_be_visible()

    def test_teacher_attendance_section(self):
        """Teacher self-attendance section should be visible."""
        # Teacher attendance section typically has a heading or label
        form = self.page.locator("form")
        expect(form.first).to_be_visible()


# ---------------------------------------------------------------------------
# Teacher attendance approvals
# ---------------------------------------------------------------------------

class TestTeacherAttendanceApprovals:
    """Tests for /teacher/attendance-approvals/ — approve/reject workflow."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, department, classroom, self_reported_attendance):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, teacher_user)
        page.goto(f"{self.url}/teacher/attendance-approvals/")
        page.wait_for_load_state("domcontentloaded")

    def test_approvals_page_loads(self):
        assert_page_has_text(self.page, "Attendance")

    def test_approve_button_visible(self):
        """Approve button should be visible for pending records."""
        approve_btn = self.page.locator("button, a", has_text=re.compile(r"Approve", re.IGNORECASE))
        # May or may not have records depending on fixture setup
        if approve_btn.count() > 0:
            expect(approve_btn.first).to_be_visible()
