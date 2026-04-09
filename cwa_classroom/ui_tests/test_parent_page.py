"""Tests for the parent list page and edit modal (CPP-94)."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.parent_page


class TestParentSidebarLink:
    """Parents link appears in admin and HoI sidebars."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page):
        self.url = live_server.url
        self.page = page

    def test_admin_has_parents_link(self, admin_user, school):
        do_login(self.page, self.url, admin_user)
        self.page.goto(f"{self.url}/admin-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(self.page, "Parents")

    def test_admin_parents_link_navigates(self, admin_user, school):
        do_login(self.page, self.url, admin_user)
        self.page.goto(f"{self.url}/admin-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        click_sidebar_link(self.page, "Parents")
        expect(self.page).to_have_url(re.compile(r"/parents"))

    def test_hoi_has_parents_link(self, hoi_user, hoi_school_setup):
        do_login(self.page, self.url, hoi_user)
        self.page.goto(f"{self.url}/dashboard/")
        # domcontentloaded is sufficient: _ensure_sidebar_visible() injects JS to
        # force Alpine.js x-show sections visible, so networkidle is not needed.
        self.page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(self.page, "Parents")


class TestParentListPage:
    """Parent list page loads and displays parents."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, enrolled_student,
               guardian, parent_with_child):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/schools/{school.id}/parents/")
        page.wait_for_load_state("networkidle")

    def test_page_loads(self):
        """Parent list page loads with heading."""
        expect(self.page.locator("h1", has_text="Manage Parents")).to_be_visible()

    def test_shows_guardian_contact(self):
        """Guardian contact appears in the list."""
        expect(self.page.locator("text=Jane Guardian")).to_be_visible()

    def test_shows_parent_account(self):
        """Parent account appears in the list."""
        expect(self.page.locator("text=Account").first).to_be_visible()

    def test_shows_contact_type(self):
        """Contact type badge is visible."""
        expect(self.page.locator("text=Contact").first).to_be_visible()

    def test_edit_button_visible(self):
        """Edit buttons are present."""
        edit_btns = self.page.locator("button[title='Edit']")
        expect(edit_btns.first).to_be_visible()

    def test_search_filters_parents(self):
        """Search via query param filters the parent list."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}/parents/?q=Jane"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Jane Guardian")).to_be_visible()


class TestGuardianEditModalEndpoint:
    """Test the guardian edit modal endpoint directly."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, enrolled_student, guardian):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.guardian = guardian
        do_login(page, self.url, admin_user)

    def test_modal_endpoint_returns_form(self):
        """The guardian edit-modal endpoint returns HTML with a form."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/guardians/{self.guardian.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("h2", has_text="Edit Guardian")).to_be_visible()

    def test_modal_shows_guardian_fields(self):
        """The edit-modal shows pre-filled guardian fields."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/guardians/{self.guardian.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("input[name='first_name']")).to_have_value("Jane")
        expect(self.page.locator("input[name='last_name']")).to_have_value("Guardian")

    def test_modal_shows_children(self):
        """The edit-modal shows linked children."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/guardians/{self.guardian.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Children")).to_be_visible()
