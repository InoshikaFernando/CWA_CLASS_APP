"""Tests for the student sidebar — class-specific links only (no maths links).

The student sidebar (sidebar_student.html) is shown on non-subject pages
like My Classes, Attendance, Join Class.  Maths-specific links are now in
sidebar_maths.html (tested separately).
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, assert_sidebar_missing_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestStudentSidebarLinks:
    """Links in the student sidebar on class-specific pages."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        # Navigate to My Classes (non-subject page → student sidebar)
        page.goto(f"{self.url}/student/my-classes/")
        page.wait_for_load_state("domcontentloaded")

    def test_home_link_visible(self):
        assert_sidebar_has_link(self.page, "Home")

    def test_home_link_navigates_to_hub(self):
        click_sidebar_link(self.page, "Home")
        expect(self.page).to_have_url(re.compile(r"/hub/"))

    def test_my_classes_link(self):
        assert_sidebar_has_link(self.page, "My Classes")

    def test_join_class_link(self):
        click_sidebar_link(self.page, "Join Class")
        expect(self.page).to_have_url(re.compile(r"/student/join"))

    def test_my_progress_link(self):
        click_sidebar_link(self.page, "My Progress")
        expect(self.page).to_have_url(re.compile(r"/student-dashboard"))

    def test_attendance_link(self):
        click_sidebar_link(self.page, "Attendance")
        self.page.wait_for_load_state("domcontentloaded")
        # May redirect to billing/module-required if attendance module not subscribed
        assert "/attendance" in self.page.url or "/billing/module-required" in self.page.url

    def test_billing_link(self):
        click_sidebar_link(self.page, "Billing")
        expect(self.page).to_have_url(re.compile(r"/billing"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


class TestStudentSidebarNoMathsOrTokenLinks:
    """Maths and Absence Token links should NOT appear in the student sidebar."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/student/my-classes/")
        page.wait_for_load_state("domcontentloaded")

    def test_no_topic_quizzes_link(self):
        assert_sidebar_missing_link(self.page, "Topic Quizzes")

    def test_no_basic_facts_link(self):
        assert_sidebar_missing_link(self.page, "Basic Facts")

    def test_no_times_tables_link(self):
        assert_sidebar_missing_link(self.page, "Times Tables")

    def test_no_absence_tokens_link(self):
        assert_sidebar_missing_link(self.page, "Absence Tokens")


class TestHubHasNoSidebar:
    """Hub page should have no sidebar for students."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/hub/")
        page.wait_for_load_state("domcontentloaded")

    def test_no_sidebar_on_hub(self):
        sidebar = self.page.locator("aside#sidebar")
        expect(sidebar).to_have_count(0)
