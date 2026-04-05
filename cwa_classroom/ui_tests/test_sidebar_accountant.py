"""Tests for the accountant sidebar — every link + collapsible sections."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestAccountantSidebarLinks:
    """Each link in sidebar_accountant.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, accountant_user, accountant_school_setup):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, accountant_user)
        page.goto(f"{self.url}/accounting/")
        page.wait_for_load_state("domcontentloaded")

    # Top-level links
    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_manage_packages_link(self):
        click_sidebar_link(self.page, "Manage Packages")
        expect(self.page).to_have_url(re.compile(r"/packages"))

    def test_user_statistics_link(self):
        click_sidebar_link(self.page, "User Statistics")
        expect(self.page).to_have_url(re.compile(r"/users"))

    def test_export_reports_link(self):
        click_sidebar_link(self.page, "Export Reports")
        expect(self.page).to_have_url(re.compile(r"/export"))

    def test_refunds_link(self):
        click_sidebar_link(self.page, "Refunds")
        expect(self.page).to_have_url(re.compile(r"/refunds"))

    def test_institute_settings_link(self):
        click_sidebar_link(self.page, "Institute Settings")
        expect(self.page).to_have_url(re.compile(r"/settings|/manage-settings|/accounting/"))

    # Invoicing section
    def test_fee_configuration_link(self):
        click_sidebar_link(self.page, "Fee Configuration")
        expect(self.page).to_have_url(re.compile(r"/invoicing/fees"))

    def test_opening_balances_link(self):
        click_sidebar_link(self.page, "Opening Balances")
        expect(self.page).to_have_url(re.compile(r"/opening-balances"))

    def test_upload_payments_link(self):
        click_sidebar_link(self.page, "Upload Bank Statements")
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

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    # Collapsible sections (scoped to aside#sidebar to avoid mobile drawer duplicates)
    def test_invoicing_section_visible(self):
        from .helpers import _ensure_sidebar_visible
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Invoicing")
        expect(toggle).to_be_visible()

    def test_salaries_section_visible(self):
        from .helpers import _ensure_sidebar_visible
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Salaries")
        expect(toggle).to_be_visible()
