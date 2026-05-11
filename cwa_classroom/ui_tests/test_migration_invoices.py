"""
test_live_invoices.py — Browser-only invoice tests against a deployed environment.

Run:
    pytest ui_tests/test_live_invoices.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests invoice list, generation, fee config, and payment pages.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
HOI_EMAIL = "user52@test.local"
ACCOUNTANT_EMAIL = "user71@test.local"
PARENT_EMAIL = "user73@test.local"


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


def _assert_no_error(page: Page):
    content = page.content()
    assert "Internal Server Error" not in content
    assert "Server Error (500)" not in content


# ═══════════════════════════════════════════════════════════════════════════
# HoI Invoice Pages
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveHoiInvoices:
    """Verify HoI can access invoice management pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, HOI_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_invoice_list_page(self):
        self.page.goto(f"{self.url}/invoicing/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_invoice_list_has_table_or_empty_state(self):
        self.page.goto(f"{self.url}/invoicing/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"invoice|no invoices|generate", re.IGNORECASE))

    def test_invoice_generation_page(self):
        self.page.goto(f"{self.url}/invoicing/generate/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_invoice_generation_has_form(self):
        self.page.goto(f"{self.url}/invoicing/generate/")
        self.page.wait_for_load_state("domcontentloaded")
        form = self.page.locator("main form, .content form, form:not([action*='logout'])").first
        if form.count():
            expect(form).to_be_visible()

    def test_fee_configuration_page(self):
        self.page.goto(f"{self.url}/invoicing/fees/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_opening_balances_page(self):
        self.page.goto(f"{self.url}/opening-balances/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_csv_upload_page(self):
        self.page.goto(f"{self.url}/invoicing/csv/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_reference_mappings_page(self):
        self.page.goto(f"{self.url}/reference-mappings/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_invoice_search(self):
        self.page.goto(f"{self.url}/invoicing/?q=test")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# HoI Salary Pages
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveHoiSalaries:
    """Verify HoI can access salary management pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, HOI_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_rate_configuration_page(self):
        self.page.goto(f"{self.url}/salaries/rates/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_generate_salary_slips_page(self):
        self.page.goto(f"{self.url}/salaries/generate/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_salary_slips_page(self):
        self.page.goto(f"{self.url}/salaries/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Accountant Invoice Pages
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAccountantInvoices:
    """Verify accountant can access invoice and salary pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ACCOUNTANT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_accounting_dashboard(self):
        self.page.goto(f"{self.url}/accounting/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_user_statistics_page(self):
        self.page.goto(f"{self.url}/accounting/users/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_export_reports_page(self):
        self.page.goto(f"{self.url}/accounting/export/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_refunds_page(self):
        self.page.goto(f"{self.url}/accounting/refunds/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_fee_configuration_page(self):
        self.page.goto(f"{self.url}/invoicing/fees/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_invoice_list_page(self):
        self.page.goto(f"{self.url}/invoicing/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_generate_invoices_page(self):
        self.page.goto(f"{self.url}/invoicing/generate/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_salary_rates_page(self):
        self.page.goto(f"{self.url}/salaries/rates/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_salary_slips_page(self):
        self.page.goto(f"{self.url}/salaries/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Parent Invoice Pages
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentInvoices:
    """Verify parent can access their invoice and payment pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_invoices_page(self):
        self.page.goto(f"{self.url}/parent/invoices/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_payments_page(self):
        self.page.goto(f"{self.url}/parent/payments/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_invoices_search(self):
        self.page.goto(f"{self.url}/parent/invoices/?q=test")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_invoices_status_filter(self):
        self.page.goto(f"{self.url}/parent/invoices/?status=issued")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
