"""Tests for the HoI / Institute Owner sidebar — every link + collapsible sections."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestHoiSidebarLinks:
    """Each link in sidebar_hoi.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/dashboard/")
        page.wait_for_load_state("domcontentloaded")

    # Top-level
    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        expect(self.page).to_have_url(re.compile(r"/school-hierarchy"))

    # Institution Setup section
    def test_schools_link(self):
        click_sidebar_link(self.page, "Schools")
        expect(self.page).to_have_url(re.compile(r"/admin-dashboard"))

    def test_departments_link(self):
        click_sidebar_link(self.page, "Departments")
        expect(self.page).to_have_url(re.compile(r"/departments"))

    def test_subjects_link(self):
        click_sidebar_link(self.page, "Subjects")
        expect(self.page).to_have_url(re.compile(r"/subject"))

    def test_academic_levels_link(self):
        click_sidebar_link(self.page, "Academic Levels")
        expect(self.page).to_have_url(re.compile(r"/subject-levels"))

    def test_classes_link(self):
        click_sidebar_link(self.page, "Classes")
        expect(self.page).to_have_url(re.compile(r"/manage-classes"))

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_ai_import_link(self):
        click_sidebar_link(self.page, "AI Import Questions")
        expect(self.page).to_have_url(re.compile(r"/ai-import"))

    # People section
    def test_teachers_link(self):
        click_sidebar_link(self.page, "Teachers")
        expect(self.page).to_have_url(re.compile(r"/teachers"))

    def test_students_link(self):
        click_sidebar_link(self.page, "Students")
        expect(self.page).to_have_url(re.compile(r"/students"))

    def test_enrollments_link(self):
        assert_sidebar_has_link(self.page, "Enrollment")

    def test_import_students_link(self):
        click_sidebar_link(self.page, "Import Students")
        expect(self.page).to_have_url(re.compile(r"/import-students"))

    def test_teacher_workload_link(self):
        click_sidebar_link(self.page, "Teacher Workload")
        expect(self.page).to_have_url(re.compile(r"/workload"))

    # Academics section
    def test_departmental_reports_link(self):
        click_sidebar_link(self.page, "Departmental Reports")
        expect(self.page).to_have_url(re.compile(r"/reports"))

    # Invoicing section
    def test_fee_configuration_link(self):
        click_sidebar_link(self.page, "Fee Configuration")
        expect(self.page).to_have_url(re.compile(r"/invoicing/fees"))

    def test_opening_balances_link(self):
        click_sidebar_link(self.page, "Opening Balances")
        expect(self.page).to_have_url(re.compile(r"/opening-balances"))

    def test_upload_payments_link(self):
        click_sidebar_link(self.page, "Upload Payments")
        expect(self.page).to_have_url(re.compile(r"/invoicing/csv"))

    def test_reference_mappings_link(self):
        click_sidebar_link(self.page, "Reference Mappings")
        expect(self.page).to_have_url(re.compile(r"/reference-mappings"))

    def test_generate_invoices_link(self):
        click_sidebar_link(self.page, "Generate Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoicing/generate"))

    def test_invoices_link(self):
        click_sidebar_link(self.page, "Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoicing/"))

    # Salaries section
    def test_rate_configuration_link(self):
        click_sidebar_link(self.page, "Rate Configuration")
        expect(self.page).to_have_url(re.compile(r"/salaries/rates"))

    def test_generate_salary_slips_link(self):
        click_sidebar_link(self.page, "Generate Salary Slips")
        expect(self.page).to_have_url(re.compile(r"/salaries/generate"))

    def test_salary_slips_link(self):
        click_sidebar_link(self.page, "Salary Slips")
        expect(self.page).to_have_url(re.compile(r"/salaries/"))

    # System section
    def test_events_link(self):
        click_sidebar_link(self.page, "Events")
        expect(self.page).to_have_url(re.compile(r"/audit/events"))

    def test_billing_link(self):
        assert_sidebar_has_link(self.page, "Billing")

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    # Collapsible sections
    def test_institution_setup_section_visible(self):
        toggle = self.page.locator("aside#sidebar button", has_text="Institution Setup")
        expect(toggle.first).to_be_visible()

    def test_invoicing_section_toggle(self):
        toggle = self.page.locator("aside#sidebar button", has_text="Invoicing")
        expect(toggle.first).to_be_visible()

    def test_salaries_section_toggle(self):
        toggle = self.page.locator("aside#sidebar button", has_text="Salaries")
        expect(toggle.first).to_be_visible()
