"""Tests for the parent sidebar — every link + child switcher."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestParentSidebarLinks:
    """Each link in sidebar_parent.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/classroom/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/classroom/parent/"))

    def test_my_children_link(self):
        click_sidebar_link(self.page, "My Children")
        expect(self.page).to_have_url(re.compile(r"/children"))

    def test_attendance_link(self):
        click_sidebar_link(self.page, "Attendance")
        expect(self.page).to_have_url(re.compile(r"/attendance"))

    def test_invoices_link(self):
        click_sidebar_link(self.page, "Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoices"))

    def test_payments_link(self):
        click_sidebar_link(self.page, "Payments")
        expect(self.page).to_have_url(re.compile(r"/payments"))

    def test_progress_link(self):
        click_sidebar_link(self.page, "Progress")
        expect(self.page).to_have_url(re.compile(r"/progress"))

    def test_billing_link(self):
        click_sidebar_link(self.page, "Billing")
        expect(self.page).to_have_url(re.compile(r"/billing"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


class TestParentChildSwitcher:
    """The child-switcher dropdown in the parent sidebar."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/classroom/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_child_switcher_button_visible(self):
        # The child switcher is the first button inside the sidebar
        switcher = self.page.locator("aside button, nav button").first
        expect(switcher).to_be_visible()

    def test_child_switcher_shows_child_name(self):
        # The switcher should show the active child's name
        sidebar = self.page.locator("aside, nav").first
        expect(sidebar).to_contain_text("ui_student")
