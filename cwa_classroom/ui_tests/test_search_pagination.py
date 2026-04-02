"""Tests for server-side search and pagination (CPP-96 + CPP-97)."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.search


class TestStudentSearch:
    """Server-side search on the students page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, enrolled_student):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.student = enrolled_student
        do_login(page, self.url, admin_user)

    def test_search_input_present(self):
        """Search input exists on the students page."""
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/students/")
        self.page.wait_for_load_state("networkidle")
        search = self.page.locator("input[name='q']")
        expect(search).to_be_visible()

    def test_search_finds_student_by_username(self):
        """Search via query param finds the student."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/"
            f"?q={self.student.username}"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator(f"text=@{self.student.username}").first).to_be_visible()

    def test_search_no_results(self):
        """Searching for nonexistent student shows empty message."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/students/"
            f"?q=ZZZZNONEXISTENT"
        )
        self.page.wait_for_load_state("networkidle")
        body = self.page.locator("body").inner_text()
        assert "No students" in body or "no students" in body.lower() or "0 of 0" in body


class TestStudentPagination:
    """Server-side pagination on the students page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, many_students):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/schools/{school.id}/students/")
        page.wait_for_load_state("networkidle")

    def test_pagination_visible(self):
        """Pagination nav appears when >25 students."""
        pagination = self.page.locator("nav[aria-label='Pagination']")
        expect(pagination).to_be_visible()

    def test_shows_correct_count(self):
        """Pagination shows total count of 30."""
        expect(self.page.locator("text=of 30")).to_be_visible()

    def test_next_page_works(self):
        """Clicking Next loads page 2."""
        next_link = self.page.locator("a", has_text="Next")
        expect(next_link).to_be_visible()
        next_link.click()
        self.page.wait_for_load_state("networkidle")
        expect(self.page).to_have_url(re.compile(r"page=2"))


class TestParentSearch:
    """Server-side search on the parents page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, enrolled_student,
               guardian, parent_with_child):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)

    def test_search_finds_guardian(self):
        """Search via query param finds the guardian."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/?q=Jane"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Jane Guardian")).to_be_visible()

    def test_search_no_results(self):
        """Searching for nonexistent parent shows empty message."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/"
            f"?q=ZZZZNONEXISTENT"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=No parents matching")).to_be_visible()
