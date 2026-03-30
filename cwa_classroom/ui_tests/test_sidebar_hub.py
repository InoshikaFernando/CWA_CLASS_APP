"""Tests for the hub sidebar (student on hub page) — every link."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestHubSidebarLinks:
    """Each link in sidebar_hub.html shown to students on the hub page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/hub/")
        page.wait_for_load_state("domcontentloaded")

    def test_home_link(self):
        assert_sidebar_has_link(self.page, "Home")

    def test_home_navigates(self):
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

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))
