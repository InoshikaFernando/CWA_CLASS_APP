"""Tests for the parent sidebar — every link + child switcher + no duplicates."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import _ensure_sidebar_visible, assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestParentSidebarLinks:
    """Each link in sidebar_parent.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/parent/"))

    def test_my_children_link(self):
        click_sidebar_link(self.page, "My Children")
        expect(self.page).to_have_url(re.compile(r"/parent/"))

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

    def test_homework_link(self):
        assert_sidebar_has_link(self.page, "Homework")

    def test_homework_navigates(self):
        click_sidebar_link(self.page, "Homework")
        expect(self.page).to_have_url(re.compile(r"/parent/homework"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    # --- No duplicate links (regression for sidebar cleanup) ---

    def test_progress_link_appears_exactly_once(self):
        """Progress link must not be duplicated in the sidebar."""
        _ensure_sidebar_visible(self.page)
        links = self.page.locator("aside#sidebar a", has_text="Progress")
        expect(links).to_have_count(1)

    def test_billing_nav_link_present(self):
        """'Billing' is a nav link pointing to /parent/billing/."""
        _ensure_sidebar_visible(self.page)
        billing_link = self.page.locator("aside#sidebar a", has_text="Billing").first
        expect(billing_link).to_be_visible()
        expect(billing_link).to_have_attribute("href", re.compile(r"/parent/billing/"))


class TestParentChildSwitcher:
    """The child-switcher dropdown in the parent sidebar."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_child_switcher_button_visible(self):
        _ensure_sidebar_visible(self.page)
        switcher = self.page.locator("aside#sidebar button").first
        expect(switcher).to_be_visible()

    def test_child_switcher_shows_child_name(self):
        _ensure_sidebar_visible(self.page)
        sidebar = self.page.locator("aside#sidebar")
        expect(sidebar).to_contain_text("Ui Student")
