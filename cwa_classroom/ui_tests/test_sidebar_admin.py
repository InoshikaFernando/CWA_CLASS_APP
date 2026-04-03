"""Tests for the admin sidebar — every link including superuser-only."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, assert_sidebar_missing_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestAdminSidebarLinks:
    """Each link in sidebar_admin.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")

    # Dashboard
    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/admin-dashboard/"))

    # People section
    def test_schools_link(self):
        assert_sidebar_has_link(self.page, "Schools")

    def test_teachers_link(self):
        click_sidebar_link(self.page, "Teachers")
        expect(self.page).to_have_url(re.compile(r"/teachers"))

    def test_students_link(self):
        click_sidebar_link(self.page, "Students")
        expect(self.page).to_have_url(re.compile(r"/students"))

    def test_parents_link(self):
        click_sidebar_link(self.page, "Parents")
        expect(self.page).to_have_url(re.compile(r"/parents"))

    def test_import_students_link(self):
        click_sidebar_link(self.page, "Import Students")
        expect(self.page).to_have_url(re.compile(r"/import-students"))

    # Academic section
    def test_academic_years_link(self):
        click_sidebar_link(self.page, "Academic Years")
        expect(self.page).to_have_url(re.compile(r"/academic-years|/terms"))

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        expect(self.page).to_have_url(re.compile(r"/school-hierarchy"))

    def test_enrollment_requests_link(self):
        click_sidebar_link(self.page, "Enrollment Requests")
        expect(self.page).to_have_url(re.compile(r"/enrollment"))

    # Questions section
    def test_browse_topics_link(self):
        click_sidebar_link(self.page, "Browse Topics")
        expect(self.page).to_have_url(re.compile(r"/topics"))

    def test_upload_questions_link(self):
        assert_sidebar_has_link(self.page, "Upload Questions")

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_ai_import_link(self):
        click_sidebar_link(self.page, "AI Import Questions")
        expect(self.page).to_have_url(re.compile(r"/ai-import"))

    # Communication section
    def test_email_link(self):
        click_sidebar_link(self.page, "Email")
        expect(self.page).to_have_url(re.compile(r"/email"))

    # Finance section
    def test_billing_link(self):
        assert_sidebar_has_link(self.page, "Billing")

    # System section
    def test_events_link(self):
        click_sidebar_link(self.page, "Events")
        expect(self.page).to_have_url(re.compile(r"/audit/events"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


class TestAdminSidebarSuperuserOnly:
    """Billing Admin link only visible for superusers."""

    def test_billing_admin_hidden_for_regular_admin(
        self, live_server, page, admin_user, school
    ):
        do_login(page, live_server.url, admin_user)
        page.goto(f"{live_server.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")
        assert_sidebar_missing_link(page, "Billing Admin")

    def test_billing_admin_visible_for_superuser(
        self, live_server, page, superuser, school
    ):
        do_login(page, live_server.url, superuser)
        page.goto(f"{live_server.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(page, "Billing Admin")
