"""
UI tests for the Currency Django-admin pages (CPP-157).

Covers:
- Currency changelist loads and shows seeded records
- Search filters the list correctly
- is_active toggle is editable inline
- Currency change-form opens and displays fields
- A new currency can be added via the admin form
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def currency(db):
    """A single active currency used in tests that need an existing row."""
    from classroom.models import Currency

    return Currency.objects.get_or_create(
        code="NZD",
        defaults={
            "name": "New Zealand Dollar",
            "symbol": "$",
            "symbol_position": "before",
            "decimal_places": 2,
            "is_active": True,
        },
    )[0]


@pytest.fixture
def inactive_currency(db):
    """An inactive currency for filter/visibility tests."""
    from classroom.models import Currency

    return Currency.objects.get_or_create(
        code="XTS",
        defaults={
            "name": "Test Currency (inactive)",
            "symbol": "X",
            "symbol_position": "before",
            "decimal_places": 2,
            "is_active": False,
        },
    )[0]


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestCurrencyChangelist:
    """Django admin /admin/classroom/currency/ — list view."""

    ADMIN_LIST_URL = "/admin/classroom/currency/"

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, superuser, currency):
        self.url = live_server.url
        self.page = page
        self.currency = currency
        do_login(page, self.url, superuser)
        page.goto(f"{self.url}{self.ADMIN_LIST_URL}")
        page.wait_for_load_state("domcontentloaded")

    # ---- page loads --------------------------------------------------------

    def test_page_title_contains_currency(self):
        """Changelist heading should mention 'Currency'."""
        body = self.page.locator("body").inner_text()
        assert "Currency" in body or "currency" in body

    def test_nzd_row_visible(self):
        """The NZD currency created by the fixture should appear."""
        assert_page_has_text(self.page, "NZD")

    def test_currency_name_visible(self):
        """Full currency name should appear in the list."""
        assert_page_has_text(self.page, "New Zealand Dollar")

    def test_symbol_column_visible(self):
        """Symbol column should show the $ symbol."""
        assert_page_has_text(self.page, "$")

    # ---- search ------------------------------------------------------------

    def test_search_by_code_filters_list(self):
        """Searching 'NZD' should keep the row visible."""
        search = self.page.locator("input[name='q']")
        search.fill("NZD")
        search.press("Enter")
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "NZD")

    def test_search_no_match_shows_empty(self):
        """Searching for a nonexistent code should show zero results text."""
        search = self.page.locator("input[name='q']")
        search.fill("ZZZNOMATCH999")
        search.press("Enter")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body").inner_text()
        # Django admin shows "0 currencies" or similar
        assert "0" in body or "no" in body.lower()

    # ---- is_active filter --------------------------------------------------

    def test_is_active_filter_exists(self):
        """Right-hand filter sidebar should have an 'is_active' filter."""
        filter_sidebar = self.page.locator("#changelist-filter")
        expect(filter_sidebar).to_be_visible()
        assert "active" in filter_sidebar.inner_text().lower()

    # ---- list_editable is_active -------------------------------------------

    def test_is_active_checkbox_present(self):
        """The is_active column should render a checkbox (list_editable)."""
        checkbox = self.page.locator(
            "input[type='checkbox'][name*='is_active']"
        ).first
        expect(checkbox).to_be_visible()

    def test_save_button_present_for_list_editable(self):
        """The 'Save' button for list_editable edits should exist."""
        save_btn = self.page.locator("input[type='submit'][name='_save'], button[name='_save']")
        if save_btn.count() == 0:
            # Django shows it as an input in some versions
            save_btn = self.page.locator("input[value='Save']")
        assert save_btn.count() > 0


class TestCurrencyChangeForm:
    """Django admin /admin/classroom/currency/<pk>/change/ — detail/edit view."""

    ADMIN_LIST_URL = "/admin/classroom/currency/"

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, superuser, currency):
        self.url = live_server.url
        self.page = page
        self.currency = currency
        do_login(page, self.url, superuser)
        # Navigate to the change form for NZD
        page.goto(f"{self.url}{self.ADMIN_LIST_URL}{currency.code}/change/")
        page.wait_for_load_state("domcontentloaded")

    def test_code_field_present(self):
        """code field should be visible (PK — read-only on change form)."""
        body = self.page.locator("body").inner_text()
        assert "NZD" in body

    def test_name_field_shows_value(self):
        """name field should display 'New Zealand Dollar'."""
        assert_page_has_text(self.page, "New Zealand Dollar")

    def test_symbol_field_shows_value(self):
        """symbol field should display '$'."""
        field = self.page.locator("input[name='symbol']")
        expect(field).to_have_value("$")

    def test_symbol_position_field_present(self):
        """symbol_position select should be present."""
        select = self.page.locator("select[name='symbol_position']")
        expect(select).to_be_visible()

    def test_decimal_places_field_present(self):
        """decimal_places field should be visible."""
        field = self.page.locator("input[name='decimal_places']")
        expect(field).to_be_visible()
        expect(field).to_have_value("2")

    def test_is_active_checkbox_checked(self):
        """is_active should be checked for an active currency."""
        checkbox = self.page.locator("input[name='is_active']")
        expect(checkbox).to_be_checked()

    def test_can_deactivate_and_reactivate(self):
        """Unchecking is_active, saving, and re-checking should persist."""
        checkbox = self.page.locator("input[name='is_active']")
        expect(checkbox).to_be_checked()

        # Deactivate
        checkbox.uncheck()
        self.page.locator("input[name='_save']").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Go back to change form and verify deactivated
        self.page.goto(
            f"{self.url}{self.ADMIN_LIST_URL}{self.currency.code}/change/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        checkbox2 = self.page.locator("input[name='is_active']")
        expect(checkbox2).not_to_be_checked()

        # Re-activate
        checkbox2.check()
        self.page.locator("input[name='_save']").click()
        self.page.wait_for_load_state("domcontentloaded")

        self.page.goto(
            f"{self.url}{self.ADMIN_LIST_URL}{self.currency.code}/change/"
        )
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("input[name='is_active']")).to_be_checked()


class TestCurrencyAdd:
    """Django admin /admin/classroom/currency/add/ — create new currency."""

    ADMIN_ADD_URL = "/admin/classroom/currency/add/"
    ADMIN_LIST_URL = "/admin/classroom/currency/"

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, superuser):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, superuser)
        page.goto(f"{self.url}{self.ADMIN_ADD_URL}")
        page.wait_for_load_state("domcontentloaded")

    def test_add_form_loads(self):
        """Add form should load without error."""
        body = self.page.locator("body").inner_text()
        assert "Currency" in body or "currency" in body

    def test_can_create_new_currency(self):
        """Fill in the add form and save — new currency should appear in list."""
        self.page.locator("input[name='code']").fill("CHF")
        self.page.locator("input[name='name']").fill("Swiss Franc")
        self.page.locator("input[name='symbol']").fill("Fr")
        self.page.locator("select[name='symbol_position']").select_option("before")
        self.page.locator("input[name='decimal_places']").fill("2")
        # is_active defaults to checked — leave it

        self.page.locator("input[name='_save']").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Should redirect to changelist after successful save
        assert "/admin/classroom/currency/" in self.page.url
        assert_page_has_text(self.page, "CHF")


