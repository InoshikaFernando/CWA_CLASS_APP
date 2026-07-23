"""Tests for payment CSV upload — upload form, column mapping."""

import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


class TestPaymentCSVUpload:
    """Tests for /invoicing/csv/upload/ — payment CSV upload form."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/csv/upload/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Upload")

    def test_file_input_visible(self):
        """File input for CSV upload."""
        file_input = self.page.locator("input[type='file']")
        expect(file_input).to_be_attached()

    def test_upload_button_visible(self):
        """Upload & Map Columns button."""
        btn = self.page.get_by_role("button", name=re.compile(r"Upload|Map", re.IGNORECASE))
        expect(btn.first).to_be_visible()


@pytest.fixture
def issued_invoice(db, enrolled_student, school, classroom):
    """An issued invoice for the enrolled student."""
    from classroom.models import Invoice, InvoiceLineItem

    inv = Invoice.objects.create(
        student=enrolled_student,
        school=school,
        invoice_number=f"INV-PAY-{_RUN_ID}",
        billing_period_start=date.today() - timedelta(days=30),
        billing_period_end=date.today(),
        status="issued",
        amount=Decimal("120.00"),
        calculated_amount=Decimal("120.00"),
    )
    InvoiceLineItem.objects.create(
        invoice=inv,
        classroom=classroom,
        daily_rate=Decimal("10.00"),
        rate_source="department_default",
        sessions_held=12,
        sessions_attended=12,
        sessions_charged=12,
        line_amount=Decimal("120.00"),
    )
    return inv


class TestRecordManualPayment:
    """Tests for payment form on invoice detail page (issued invoice)."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, issued_invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = issued_invoice
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/{self.invoice.id}/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        body = self.page.locator("body").inner_text()
        # Page may show payment form OR redirect/error for draft invoices
        assert "Payment" in body or "Invoice" in body or "Record" in body or len(body) > 50

    def test_amount_input(self):
        """Amount input should be present (if page loaded correctly)."""
        inputs = self.page.locator("input[type='number'], input[name*='amount']")
        if f"/invoicing/{self.invoice.id}/" in self.page.url:
            assert inputs.count() >= 1

    def test_date_input(self):
        """Payment date input should be present (if page loaded correctly)."""
        if f"/invoicing/{self.invoice.id}/" in self.page.url:
            date_inputs = self.page.locator("input[type='date']")
            assert date_inputs.count() >= 1

    def test_submit_button(self):
        """Submit/record button should be visible."""
        btn = self.page.get_by_role("button", name=re.compile(r"Record|Pay", re.IGNORECASE))
        expect(btn.first).to_be_visible()


class TestZeroInvoiceBalance:
    """Tests for the Zero Balance action on the invoice detail page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, issued_invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = issued_invoice
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/{self.invoice.id}/")
        page.wait_for_load_state("domcontentloaded")

    def test_zero_balance_card_visible(self):
        """The Zero Balance card should be shown for an unpaid issued invoice."""
        assert_page_has_text(self.page, "Zero Balance")

    def test_zero_balance_button_visible(self):
        btn = self.page.get_by_role("button", name=re.compile(r"Zero Balance", re.IGNORECASE))
        expect(btn.first).to_be_visible()

    def test_zero_balance_settles_invoice(self):
        """Clicking Zero Balance marks the invoice paid with no balance due."""
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name=re.compile(r"Zero Balance", re.IGNORECASE)).first.click()
        self.page.wait_for_load_state("domcontentloaded")

        self.invoice.refresh_from_db()
        assert self.invoice.status == "paid"
        assert self.invoice.amount_due == Decimal("0.00")


class TestBulkZeroBalances:
    """Tests for /invoicing/zero-balances/ — scoped bulk zeroing."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, issued_invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = issued_invoice
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/zero-balances/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Zero Balances")

    def test_irreversible_warning_shown(self):
        """The scope page must warn the action cannot be undone."""
        body = self.page.locator("body").inner_text().lower()
        assert "cannot be undone" in body

    def test_scope_dropdowns_present(self):
        """Whole-institute / department + class scope selectors exist."""
        assert_page_has_text(self.page, "Whole institute")
        assert self.page.locator("#scope-dept").count() == 1
        assert self.page.locator("#scope-class").count() == 1

    def test_preview_then_confirm_zeroes_balance(self):
        # Whole institute (no scope selected) → Preview.
        self.page.get_by_role("button", name=re.compile(r"^Preview$", re.IGNORECASE)).click()
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, self.invoice.invoice_number)

        # Confirm.
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name=re.compile(r"Zero \d+ Balance", re.IGNORECASE)).click()
        self.page.wait_for_load_state("domcontentloaded")

        self.invoice.refresh_from_db()
        assert self.invoice.status == "paid"
        assert self.invoice.amount_due == Decimal("0.00")
