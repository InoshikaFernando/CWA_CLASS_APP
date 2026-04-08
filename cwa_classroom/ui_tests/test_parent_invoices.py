"""Tests for parent invoice view with search and filters (CPP-95)."""

import re
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.parent_invoice


class TestParentInvoicesView:
    """Parent can see, search, and filter child invoices."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, enrolled_student, school, invoice):
        self.url = live_server.url
        self.page = page
        self.parent = parent_with_child
        self.school = school
        # Issue the invoice so parent can see it
        invoice.status = "issued"
        invoice.save(update_fields=["status"])
        self.invoice = invoice

        do_login(page, self.url, parent_with_child)
        # Navigate directly to invoices page and wait
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_page_loads(self):
        """Invoice page loads with heading."""
        expect(self.page.locator("h1", has_text="Invoices")).to_be_visible()

    def test_shows_invoice(self):
        """The issued invoice appears in the list."""
        expect(self.page.locator(f"text={self.invoice.invoice_number}")).to_be_visible()

    def test_search_input_present(self):
        """Search input exists."""
        search = self.page.locator("input[name='q']")
        expect(search).to_be_visible()

    def test_status_filter_present(self):
        """Status filter dropdown exists."""
        status = self.page.locator("select[name='status']")
        expect(status).to_be_visible()

    def test_search_finds_invoice(self):
        """Search via query param finds the invoice."""
        inv_num = self.invoice.invoice_number
        self.page.goto(f"{self.url}/parent/invoices/?q={inv_num}")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator(f"text={inv_num}")).to_be_visible()

    def test_search_no_results(self):
        """Searching for nonexistent invoice shows empty state."""
        self.page.goto(f"{self.url}/parent/invoices/?q=NONEXISTENT-999")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=No invoices matching")).to_be_visible()

    def test_invoice_links_to_detail(self):
        """Clicking invoice number navigates to detail page."""
        link = self.page.locator(f"a:has-text('{self.invoice.invoice_number}')")
        link.click()
        self.page.wait_for_load_state("networkidle")
        expect(self.page).to_have_url(re.compile(r"/parent/invoices/\d+"))
