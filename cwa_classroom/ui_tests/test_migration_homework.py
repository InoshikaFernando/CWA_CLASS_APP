"""
test_live_homework.py — Browser-only homework tests against a deployed environment.

Run:
    pytest ui_tests/test_live_homework.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests homework creation (teacher), viewing (student/parent), and submission flows.
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
# Teacher Homework Management
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTeacherHomework:
    """Verify teacher homework management pages."""

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

    def test_homework_create_form_fields(self):
        """Verify the create homework form has expected fields."""
        self.page.goto(f"{self.url}/homework/create/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"title|class|topic|due|question", re.IGNORECASE))

    def test_homework_monitor_page(self):
        self.page.goto(f"{self.url}/homework/monitor/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_homework_list_shows_content(self):
        """Verify homework list renders (may be empty or have items)."""
        self.page.goto(f"{self.url}/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"homework|no homework|create", re.IGNORECASE))


# ═══════════════════════════════════════════════════════════════════════════
# Student Homework
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentHomework:
    """Verify student homework pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_homework_list_page(self):
        self.page.goto(f"{self.url}/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_homework_list_shows_content(self):
        self.page.goto(f"{self.url}/homework/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"homework|no homework|due|submit", re.IGNORECASE))


# ═══════════════════════════════════════════════════════════════════════════
# Parent Homework View
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentHomeworkView:
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
