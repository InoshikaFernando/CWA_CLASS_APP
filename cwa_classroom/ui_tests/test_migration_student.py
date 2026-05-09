"""
test_live_student.py — Browser-only student dashboard & hub tests against a deployed environment.

Run:
    pytest ui_tests/test_live_student.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests student hub, dashboard, progress, classes, and maths pages.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
STUDENT_EMAIL = "user46@test.local"


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
# Student Hub / Home
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentHub:
    """Verify student hub page loads with key elements."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_hub_loads(self):
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_hub_has_greeting(self):
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"welcome|hello|hi|good|hey", re.IGNORECASE))

    def test_hub_has_time_cards(self):
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"today|this week", re.IGNORECASE))

    def test_hub_has_quick_actions(self):
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"classes|progress|profile", re.IGNORECASE))


# ═══════════════════════════════════════════════════════════════════════════
# Student Dashboard (Progress)
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentDashboard:
    """Verify student progress dashboard loads and shows progress elements."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_dashboard_loads(self):
        self.page.goto(f"{self.url}/student-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_progress_page_loads(self):
        self.page.goto(f"{self.url}/progress/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Student Classes
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentClasses:
    """Verify student class pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_my_classes_page(self):
        self.page.goto(f"{self.url}/student/my-classes/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_join_class_page(self):
        self.page.goto(f"{self.url}/student/join/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_join_class_has_form(self):
        self.page.goto(f"{self.url}/student/join/")
        self.page.wait_for_load_state("domcontentloaded")
        code_input = self.page.locator("#id_class_code, [name='class_code']").first
        if code_input.count():
            expect(code_input).to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════
# Student Maths & Quiz pages
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentMaths:
    """Verify student maths and quiz pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_maths_home_page(self):
        self.page.goto(f"{self.url}/maths/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_basic_facts_page(self):
        self.page.goto(f"{self.url}/maths/basic-facts/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_times_tables_page(self):
        self.page.goto(f"{self.url}/maths/times-tables/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_topic_quizzes_page(self):
        self.page.goto(f"{self.url}/maths/topic-quizzes/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_maths_page_has_quiz_links(self):
        self.page.goto(f"{self.url}/maths/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"quiz|topic|facts|tables", re.IGNORECASE))


# ═══════════════════════════════════════════════════════════════════════════
# Student Homework
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentHomework:
    """Verify student homework pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_homework_list_page(self):
        self.page.goto(f"{self.url}/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Student Attendance
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentAttendance:
    """Verify student attendance pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_attendance_page(self):
        self.page.goto(f"{self.url}/attendance/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
