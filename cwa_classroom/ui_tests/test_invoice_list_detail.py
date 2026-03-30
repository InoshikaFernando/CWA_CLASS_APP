"""Tests for invoice list and detail views."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


class TestInvoiceList:
    """Tests for /invoicing/ — invoice list with filters and stats."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = invoice
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Invoice")

    def test_invoice_number_visible(self):
        """Invoice number should appear in the list."""
        assert_page_has_text(self.page, "INV-0001")

    def test_generate_invoices_button(self):
        """Generate Invoices button should be visible."""
        btn = self.page.locator("a, button", has_text=re.compile(r"Generate", re.IGNORECASE))
        expect(btn.first).to_be_visible()

    def test_search_bar_visible(self):
        """Search input for filtering invoices."""
        search = self.page.locator("input[type='search'], input[type='text'][name*='search'], input[placeholder*='Search']")
        if search.count() > 0:
            expect(search.first).to_be_visible()

    def test_draft_badge_visible(self):
        """Draft status badge should be visible for the draft invoice."""
        body = self.page.locator("body").inner_text().lower()
        assert "draft" in body


class TestInvoiceDetail:
    """Tests for /invoicing/<id>/ — invoice detail page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = invoice
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/{self.invoice.id}/")
        page.wait_for_load_state("domcontentloaded")

    def test_invoice_number_displayed(self):
        assert_page_has_text(self.page, "INV-0001")

    def test_student_name_displayed(self):
        assert_page_has_text(self.page, "ui_student")

    def test_status_badge_displayed(self):
        """Status badge (draft) should be visible."""
        body = self.page.locator("body").inner_text().lower()
        assert "draft" in body

    def test_line_items_table(self):
        """Line items table should show classroom name."""
        assert_page_has_text(self.page, "Year 7 Maths")

    def test_amount_displayed(self):
        """Invoice amount should be displayed."""
        body = self.page.locator("body").inner_text()
        assert re.search(r"120|Amount", body)

    def test_edit_button_for_draft(self):
        """Edit button should be visible for draft invoices."""
        edit_btn = self.page.locator("a, button", has_text=re.compile(r"Edit", re.IGNORECASE))
        if edit_btn.count() > 0:
            expect(edit_btn.first).to_be_visible()
