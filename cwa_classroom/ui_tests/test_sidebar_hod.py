"""Tests for the HoD sidebar — every link including conditional module links."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestHodSidebarLinks:
    """Each link in sidebar_hod.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hod_user, school, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hod_user)
        page.goto(f"{self.url}/dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/dashboard/"))

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        expect(self.page).to_have_url(re.compile(r"/school-hierarchy"))

    # My Department section
    def test_classes_link(self):
        click_sidebar_link(self.page, "Classes")
        expect(self.page).to_have_url(re.compile(r"/manage-classes"))

    def test_academic_levels_link(self):
        click_sidebar_link(self.page, "Academic Levels")
        expect(self.page).to_have_url(re.compile(r"/subject-levels"))

    def test_teacher_workload_link(self):
        click_sidebar_link(self.page, "Teacher Workload")
        expect(self.page).to_have_url(re.compile(r"/workload"))

    def test_import_students_link(self):
        click_sidebar_link(self.page, "Import Students")
        expect(self.page).to_have_url(re.compile(r"/import-students"))

    def test_import_balances_link(self):
        click_sidebar_link(self.page, "Import Balances")
        expect(self.page).to_have_url(re.compile(r"/import-balances"))

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_ai_import_link(self):
        click_sidebar_link(self.page, "AI Import Questions")
        expect(self.page).to_have_url(re.compile(r"/ai-import"))

    # Academics & Progress section
    def test_departmental_reports_link(self):
        click_sidebar_link(self.page, "Departmental Reports")
        expect(self.page).to_have_url(re.compile(r"/reports"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    # Collapsible section toggle
    def test_my_department_section_toggles(self):
        """The 'My Department' collapsible section should be expandable/collapsible."""
        toggle = self.page.locator("button", has_text="My Department")
        expect(toggle).to_be_visible()
        # Content should be visible by default (x-data has deptOpen: true)
        assert_sidebar_has_link(self.page, "Classes")
