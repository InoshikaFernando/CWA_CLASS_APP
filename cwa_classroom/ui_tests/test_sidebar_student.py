"""Tests for the student sidebar — every link, conditional maths links, trial banner."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, assert_sidebar_missing_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


# ---------------------------------------------------------------------------
# Always-visible links
# ---------------------------------------------------------------------------

class TestStudentSidebarLinks:
    """Each link in sidebar_student.html that is always visible."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/hub/")
        page.wait_for_load_state("domcontentloaded")

    def test_home_link_visible(self):
        assert_sidebar_has_link(self.page, "Home")

    def test_home_link_navigates(self):
        click_sidebar_link(self.page, "Home")
        expect(self.page).to_have_url(re.compile(r"/hub/"))

    def test_my_classes_link(self):
        click_sidebar_link(self.page, "My Classes")
        expect(self.page).to_have_url(re.compile(r"/student/my-classes"))

    def test_join_class_link(self):
        click_sidebar_link(self.page, "Join Class")
        expect(self.page).to_have_url(re.compile(r"/student/join"))

    def test_my_progress_link(self):
        click_sidebar_link(self.page, "My Progress")
        expect(self.page).to_have_url(re.compile(r"/student-dashboard"))

    def test_attendance_link(self):
        click_sidebar_link(self.page, "Attendance")
        expect(self.page).to_have_url(re.compile(r"/student/attendance"))

    def test_billing_link(self):
        click_sidebar_link(self.page, "Billing")
        expect(self.page).to_have_url(re.compile(r"/billing"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


# ---------------------------------------------------------------------------
# Conditional maths links (only visible on /maths/ paths)
# ---------------------------------------------------------------------------

class TestStudentSidebarMathsLinks:
    """Maths-specific sidebar links that only appear when on /maths/ path."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_maths_links_hidden_on_hub(self):
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_sidebar_missing_link(self.page, "Topic Quizzes")
        assert_sidebar_missing_link(self.page, "Basic Facts")
        assert_sidebar_missing_link(self.page, "Times Tables")

    def test_maths_links_visible_on_maths_page(self):
        self.page.goto(f"{self.url}/maths/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(self.page, "Topic Quizzes")
        assert_sidebar_has_link(self.page, "Basic Facts")
        assert_sidebar_has_link(self.page, "Times Tables")
