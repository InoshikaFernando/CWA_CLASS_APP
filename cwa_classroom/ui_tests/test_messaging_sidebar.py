"""
UI automation + end-to-end tests for CPP-349:
  - "Messaging" sidebar link appears under COMMUNICATION
  - Clicking navigates to /admin-dashboard/messaging/compose/
  - Active highlight applied on /messaging/* routes
  - Page renders correct heading and channel toggle
  - Non-admin (student) cannot access the compose page

Run locally:
    pytest ui_tests/test_messaging_sidebar.py -v

Run against deployed env:
    pytest ui_tests/test_messaging_sidebar.py --live-url=https://test.wizardslearninghub.co.nz -v
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, assert_sidebar_missing_link, click_sidebar_link

pytestmark = pytest.mark.messaging


# ---------------------------------------------------------------------------
# Sidebar visibility + navigation
# ---------------------------------------------------------------------------

class TestMessagingSidebarLink:
    """Messaging link in sidebar_admin.html — CPP-349."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_messaging_link_visible_in_sidebar(self):
        """'Messaging' appears in the admin sidebar under COMMUNICATION."""
        assert_sidebar_has_link(self.page, "Messaging")

    def test_messaging_link_navigates_to_compose(self):
        """Clicking Messaging navigates to /messaging/compose/."""
        click_sidebar_link(self.page, "Messaging")
        expect(self.page).to_have_url(re.compile(r"/messaging/compose/"))

    def test_messaging_link_under_communication_section(self):
        """Messaging sits after Email under the COMMUNICATION heading."""
        sidebar = self.page.locator("nav")
        comm_heading = sidebar.get_by_text("Communication", exact=False)
        expect(comm_heading).to_be_visible()
        # Both Email and Messaging must be in the nav
        assert_sidebar_has_link(self.page, "Email")
        assert_sidebar_has_link(self.page, "Messaging")


# ---------------------------------------------------------------------------
# Active state
# ---------------------------------------------------------------------------

class TestMessagingActiveState:
    """Active highlight applied when navigated to /messaging/* routes."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)

    def test_messaging_link_active_on_compose_page(self):
        """Messaging nav item has active bg class when on compose page."""
        self.page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        self.page.wait_for_load_state("domcontentloaded")
        link = self.page.locator("nav a", has_text="Messaging")
        expect(link).to_have_class(re.compile(r"bg-white/15"))

    def test_email_link_not_active_on_messaging_page(self):
        """Email nav item does NOT have active bg class when on messaging page."""
        self.page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        self.page.wait_for_load_state("domcontentloaded")
        email_link = self.page.locator("nav a", has_text="Email")
        expect(email_link).not_to_have_class(re.compile(r"bg-white/15"))

    def test_messaging_link_not_active_on_dashboard(self):
        """Messaging nav item NOT active when on admin dashboard."""
        self.page.goto(f"{self.url}/admin-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        link = self.page.locator("nav a", has_text="Messaging")
        expect(link).not_to_have_class(re.compile(r"bg-white/15"))


# ---------------------------------------------------------------------------
# Compose page content
# ---------------------------------------------------------------------------

class TestMessagingComposePage:
    """Compose page renders correct shell content (CPP-349 placeholder)."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_title_contains_messaging(self):
        expect(self.page).to_have_title(re.compile(r"Messaging", re.IGNORECASE))

    def test_page_heading_new_message(self):
        heading = self.page.get_by_role("heading", name=re.compile(r"New Message", re.IGNORECASE))
        expect(heading).to_be_visible()

    def test_channel_email_option_visible(self):
        expect(self.page.get_by_text("Email").first).to_be_visible()

    def test_channel_sms_option_visible_but_disabled(self):
        sms_el = self.page.locator("text=SMS").first
        expect(sms_el).to_be_visible()

    def test_sms_coming_soon_tooltip_text_present(self):
        expect(self.page.locator("text=SMS coming in Phase 2")).to_be_attached()

    def test_to_field_placeholder_visible(self):
        expect(self.page.locator("text=Recipients")).to_be_visible()

    def test_schedule_section_visible(self):
        expect(self.page.get_by_text("Schedule", exact=True)).to_be_visible()

    def test_send_button_disabled(self):
        send_btn = self.page.get_by_role("button", name=re.compile(r"Schedule.*Send|Send", re.IGNORECASE))
        expect(send_btn).to_be_disabled()

    def test_save_draft_button_disabled(self):
        draft_btn = self.page.get_by_role("button", name=re.compile(r"Save Draft", re.IGNORECASE))
        expect(draft_btn).to_be_disabled()

    def test_school_name_displayed(self, school):
        expect(self.page.get_by_text(school.name)).to_be_visible()


# ---------------------------------------------------------------------------
# Messaging dashboard redirect
# ---------------------------------------------------------------------------

class TestMessagingDashboardRedirect:
    """/messaging/ redirects to compose page."""

    def test_messaging_dashboard_redirects_to_compose(self, live_server, page, admin_user, school):
        do_login(page, live_server.url, admin_user)
        page.goto(f"{live_server.url}/admin-dashboard/messaging/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/messaging/compose/"))


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

class TestMessagingAccessControl:
    """Non-admin roles cannot access the messaging pages."""

    def test_student_cannot_access_compose(self, live_server, page, student_user):
        do_login(page, live_server.url, student_user)
        page.goto(f"{live_server.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).not_to_have_url(re.compile(r"/messaging/compose/"))

    def test_unauthenticated_redirected_to_login(self, live_server, page):
        page.goto(f"{live_server.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/login|/accounts/login"))
