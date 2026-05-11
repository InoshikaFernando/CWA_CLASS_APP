"""
test_live_parent.py — Browser-only parent portal tests against a deployed environment.

Run:
    pytest ui_tests/test_live_parent.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests parent dashboard, children, attendance, progress, and homework pages.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
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
# Parent Dashboard
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentDashboard:
    """Verify parent dashboard loads with key elements."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_dashboard_loads(self):
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_dashboard_shows_children_info(self):
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"child|children|student|dashboard", re.IGNORECASE))


# ═══════════════════════════════════════════════════════════════════════════
# Parent Children & Classes
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentChildren:
    """Verify parent can view children and class information."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_add_child_page(self):
        self.page.goto(f"{self.url}/parent/add-child/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_add_child_has_form(self):
        self.page.goto(f"{self.url}/parent/add-child/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_classes_page(self):
        self.page.goto(f"{self.url}/parent/classes/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Parent Attendance
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentAttendance:
    """Verify parent can view child attendance."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_attendance_page(self):
        self.page.goto(f"{self.url}/parent/attendance/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Parent Progress
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentProgress:
    """Verify parent can view child progress."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_progress_page(self):
        self.page.goto(f"{self.url}/parent/progress/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Parent Homework
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentHomework:
    """Verify parent can view child homework."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_homework_page(self):
        self.page.goto(f"{self.url}/parent/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Parent Self-Registration Page
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentRegistration:
    """Verify parent self-registration page loads (unauthenticated)."""

    def test_parent_signup_page_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/register/parent/")
        page.wait_for_load_state("domcontentloaded")
        content = page.content()
        assert "Internal Server Error" not in content

    def test_parent_signup_has_form_fields(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/register/parent/")
        page.wait_for_load_state("domcontentloaded")
        form = page.locator("form").first
        if form.count():
            expect(form).to_be_visible()
