"""Tests for invoice generation form."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


class TestGenerateInvoices:
    """Tests for /invoicing/generate/ — invoice generation form."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/generate/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Generate")

    def test_billing_period_start_input(self):
        """Billing period start date input should exist."""
        date_inputs = self.page.locator("input[type='date']")
        assert date_inputs.count() >= 1

    def test_billing_period_end_input(self):
        """Billing period end date input should exist."""
        date_inputs = self.page.locator("input[type='date']")
        assert date_inputs.count() >= 2

    def test_billing_type_options(self):
        """Billing type radio buttons (Post-Term / Upfront) should exist."""
        radios = self.page.locator("input[type='radio']")
        assert radios.count() >= 1

    def test_submit_button(self):
        """Generate/preview button should be visible."""
        btn = self.page.get_by_role("button", name=re.compile(r"Generate|Preview", re.IGNORECASE))
        expect(btn.first).to_be_visible()

    def test_back_link(self):
        """Back link should be present."""
        back = self.page.locator("a[href*='invoicing']")
        assert back.count() >= 1
