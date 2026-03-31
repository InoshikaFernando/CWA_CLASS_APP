"""Tests for the student hub dashboard — greeting, time cards, quick actions, subject cards."""

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_card_visible, assert_page_has_text

pytestmark = pytest.mark.dashboard


class TestHubDashboardRendering:
    """Verify all sections of hub/home.html render correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, timelog, future_session):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/hub/")
        page.wait_for_load_state("domcontentloaded")

    def test_greeting_renders(self):
        """Greeting card with user's first name or username."""
        assert_page_has_text(self.page, "ui_student")

    def test_daily_time_card_renders(self):
        """Daily time card (sky-blue) shows formatted time."""
        assert_page_has_text(self.page, "Today")

    def test_weekly_time_card_renders(self):
        """Weekly time card (violet) shows formatted time."""
        assert_page_has_text(self.page, "This Week")

    def test_upcoming_classes_card_renders(self):
        """Upcoming classes card shows class name."""
        assert_page_has_text(self.page, "Upcoming")

    def test_quick_action_my_classes_visible(self):
        """Quick action grid renders My Classes card."""
        assert_page_has_text(self.page, "My Classes")

    def test_quick_action_join_class_visible(self):
        assert_page_has_text(self.page, "Join Class")

    def test_quick_action_progress_visible(self):
        assert_page_has_text(self.page, "Progress")

    def test_quick_action_attendance_visible(self):
        assert_page_has_text(self.page, "Attendance")

    def test_quick_action_profile_visible(self):
        assert_page_has_text(self.page, "Profile")

    def test_subject_card_renders(self):
        """Subject card for enrolled Mathematics class."""
        assert_page_has_text(self.page, "Mathematics")
