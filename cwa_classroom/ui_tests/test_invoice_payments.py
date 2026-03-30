"""Tests for payment CSV upload — upload form, column mapping."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
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
        btn = self.page.locator("button[type='submit'], input[type='submit']")
        expect(btn.first).to_be_visible()


class TestRecordManualPayment:
    """Tests for /invoicing/<id>/pay/ — manual payment recording."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = invoice
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/{self.invoice.id}/pay/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Payment")

    def test_amount_input(self):
        """Amount input should be present."""
        inputs = self.page.locator("input[type='number'], input[name*='amount']")
        assert inputs.count() >= 1

    def test_date_input(self):
        """Payment date input should be present."""
        date_inputs = self.page.locator("input[type='date']")
        assert date_inputs.count() >= 1

    def test_submit_button(self):
        """Submit/record button should be visible."""
        btn = self.page.locator("button[type='submit'], input[type='submit']")
        expect(btn.first).to_be_visible()
