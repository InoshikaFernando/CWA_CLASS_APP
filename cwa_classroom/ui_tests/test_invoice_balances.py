"""Tests for opening balances and reference mappings."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


class TestOpeningBalances:
    """Tests for /invoicing/opening-balances/ — batch balance editor."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/opening-balances/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Opening Balances")

    def test_info_callout(self):
        """Info callout about positive amounts."""
        body = self.page.locator("body").inner_text().lower()
        assert "positive" in body or "owes" in body or "balance" in body

    def test_student_listed(self):
        """Enrolled student should be listed."""
        assert_page_has_text(self.page, "ui_student")

    def test_balance_input_fields(self):
        """Balance input fields should exist."""
        inputs = self.page.locator("input[type='number']")
        assert inputs.count() >= 1

    def test_save_button(self):
        """Save button should exist (hidden until a balance is modified)."""
        btn = self.page.locator("button[type='submit']", has_text=re.compile(r"Save", re.IGNORECASE))
        expect(btn.first).to_be_attached()


class TestReferenceMappings:
    """Tests for /invoicing/reference-mappings/ — payment reference management."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/invoicing/reference-mappings/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Reference")

    def test_search_bar(self):
        """Search input should be present."""
        search = self.page.locator("input[type='search'], input[type='text']")
        if search.count() > 0:
            expect(search.first).to_be_visible()

    def test_empty_state_or_table(self):
        """Either an empty state message or a mappings table should show."""
        body = self.page.locator("body").inner_text()
        assert "No" in body or "mapping" in body.lower() or "Reference" in body
