"""Tests for fee configuration — class fees table, batch update, student overrides."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


class TestFeeConfiguration:
    """Tests for /invoicing/fees/ — fee configuration page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/fees/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Fee")

    def test_class_fees_table_renders(self):
        """Class fees table should show classroom names."""
        assert_page_has_text(self.page, "Year 7 Maths")

    def test_fee_input_fields(self):
        """Fee input fields (number type) should be present."""
        inputs = self.page.locator("input[type='number']")
        assert inputs.count() >= 1

    def test_source_badges_render(self):
        """Source indicators (Inherited / Not set) should be visible."""
        body = self.page.locator("body").inner_text()
        assert "Inherited" in body or "Not set" in body or "override" in body.lower()

    def test_save_button_exists(self):
        """Save All Changes button should exist (hidden until a fee is modified)."""
        btn = self.page.locator("button[type='submit']", has_text=re.compile(r"Save", re.IGNORECASE))
        expect(btn.first).to_be_attached()

    def test_student_override_section(self):
        """Student fee override section should be present."""
        assert_page_has_text(self.page, "Override")
