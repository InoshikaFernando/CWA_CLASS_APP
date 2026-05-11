"""
test_live_attendance.py — Browser-only attendance tests against a deployed environment.

Run:
    pytest ui_tests/test_live_attendance.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests attendance pages for students, teachers, and parents.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
TEACHER_EMAIL = "user45@test.local"
STUDENT_EMAIL = "user46@test.local"
PARENT_EMAIL = "user73@test.local"


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


def _assert_no_error(page: Page):
    content = page.content()
    assert "Internal Server Error" not in content
    assert "Server Error (500)" not in content


# ═══════════════════════════════════════════════════════════════════════════
# Student Attendance
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentAttendance:
    """Verify student attendance history page."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_attendance_page_loads(self):
        self.page.goto(f"{self.url}/attendance/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_attendance_shows_stats_or_empty(self):
        self.page.goto(f"{self.url}/attendance/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(
            r"attendance|session|present|absent|no attendance|module",
            re.IGNORECASE,
        ))


# ═══════════════════════════════════════════════════════════════════════════
# Teacher Attendance
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTeacherAttendance:
    """Verify teacher attendance management pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, TEACHER_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_attendance_approvals_page(self):
        self.page.goto(f"{self.url}/teacher/attendance-approvals/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Parent Attendance
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentAttendance:
    """Verify parent attendance view page."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_attendance_page_loads(self):
        self.page.goto(f"{self.url}/parent/attendance/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
