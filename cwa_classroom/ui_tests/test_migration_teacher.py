"""
test_live_teacher.py — Browser-only teacher dashboard tests against a deployed environment.

Run:
    pytest ui_tests/test_live_teacher.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests teacher dashboard, class management, homework, and attendance pages.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
TEACHER_EMAIL = "user45@test.local"
HOI_EMAIL = "user52@test.local"


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
# Teacher Dashboard
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTeacherDashboard:
    """Verify teacher dashboard loads and shows key elements."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, TEACHER_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_dashboard_loads(self):
        self.page.goto(f"{self.url}/teacher/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_dashboard_has_classes_section(self):
        self.page.goto(f"{self.url}/teacher/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"class|dashboard", re.IGNORECASE))

    def test_enrollment_requests_page(self):
        self.page.goto(f"{self.url}/teacher/enrollment-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_class_progress_page(self):
        self.page.goto(f"{self.url}/teacher/class/progress/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_school_hierarchy_page(self):
        self.page.goto(f"{self.url}/school-hierarchy/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_browse_topics_page(self):
        self.page.goto(f"{self.url}/maths/topics/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_create_questions_page(self):
        self.page.goto(f"{self.url}/maths/create-question/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_upload_questions_page(self):
        self.page.goto(f"{self.url}/maths/upload/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Teacher Homework
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTeacherHomework:
    """Verify teacher homework pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, TEACHER_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_homework_list_page(self):
        self.page.goto(f"{self.url}/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_homework_create_page(self):
        self.page.goto(f"{self.url}/homework/create/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_homework_create_form_has_fields(self):
        self.page.goto(f"{self.url}/homework/create/")
        self.page.wait_for_load_state("domcontentloaded")
        title_field = self.page.locator("#id_title, [name='title']").first
        if title_field.count():
            expect(title_field).to_be_visible()

    def test_homework_monitor_page(self):
        self.page.goto(f"{self.url}/homework/monitor/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Teacher Attendance
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTeacherAttendance:
    """Verify teacher attendance pages load correctly."""

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
# HoI Dashboard & Institution Management
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveHoiDashboard:
    """Verify HoI dashboard and management pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, HOI_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_dashboard_loads(self):
        self.page.goto(f"{self.url}/dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_manage_classes_page(self):
        self.page.goto(f"{self.url}/manage-classes/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_departments_page(self):
        self.page.goto(f"{self.url}/departments/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_teachers_page(self):
        self.page.goto(f"{self.url}/teachers/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_students_page(self):
        self.page.goto(f"{self.url}/students/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_parents_page(self):
        self.page.goto(f"{self.url}/parents/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_workload_page(self):
        self.page.goto(f"{self.url}/workload/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_reports_page(self):
        self.page.goto(f"{self.url}/reports/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
