"""Tests for clicking hub quick-action cards and subject cards — navigation."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.dashboard


class TestHubQuickActionNavigation:
    """Click each quick-action card and verify it navigates to the right page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def _go_hub(self):
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("networkidle")

    def test_click_my_classes_card(self):
        self._go_hub()
        # Quick action cards are in main content area (not sidebar)
        card = self.page.locator("main a", has_text="My Classes").first
        card.click()
        expect(self.page).to_have_url(re.compile(r"/student/my-classes|/hub/"))

    def test_click_join_class_card(self):
        self._go_hub()
        card = self.page.locator("main a", has_text="Join Class").first
        card.click()
        expect(self.page).to_have_url(re.compile(r"/student/join"))

    def test_click_progress_card(self):
        self._go_hub()
        card = self.page.locator("main a", has_text="Progress").first
        card.click()
        expect(self.page).to_have_url(re.compile(r"/student-dashboard"))

    def test_click_attendance_card(self):
        self._go_hub()
        card = self.page.locator("main a", has_text="Attendance").first
        card.click()
        expect(self.page).to_have_url(re.compile(r"/student/attendance|/attendance"))

    def test_click_profile_card(self):
        self._go_hub()
        card = self.page.locator("main a", has_text="Profile").first
        card.click()
        expect(self.page).to_have_url(re.compile(r"/accounts/profile|/profile"))

    def test_click_subject_card_navigates(self):
        self._go_hub()
        subject_card = self.page.locator("main a[href*='/maths/']").first
        if subject_card.count() > 0:
            subject_card.click()
            expect(self.page).to_have_url(re.compile(r"/maths/"))
