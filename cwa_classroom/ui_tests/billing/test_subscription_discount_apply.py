"""Granting a school a discount code from the super-admin billing page.

Until this existed the page offered plan, trial, invoice-counter and status
overrides but nothing for a discount code, so attaching a negotiated deal to
an existing school meant editing the row in Django admin. These drive the
control itself: the select is rendered with the school's current code chosen,
applying one is reflected back on the page, and "No discount" clears it.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login
from ..helpers import assert_page_has_text


@pytest.fixture
def full_discount(db):
    """A 100%-off institute code — the "this school pays nothing" grant."""
    from billing.models import InstituteDiscountCode

    return InstituteDiscountCode.objects.create(
        code="UITESTFREE100",
        description="UI test — fully free",
        discount_percent=100,
    )


class TestApplyDiscountCode:
    """/admin-dashboard/billing/subscriptions/<pk>/ — discount override."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, superuser, school, full_discount):
        self.url = live_server.url
        self.page = page
        self.sub = school.subscription
        self.code = full_discount
        do_login(page, self.url, superuser)
        self._open()

    def _open(self):
        self.page.goto(
            f"{self.url}/admin-dashboard/billing/subscriptions/{self.sub.pk}/"
        )
        self.page.wait_for_load_state("domcontentloaded")

    def _select(self):
        return self.page.locator("select[name='discount_code_id']")

    def _apply(self):
        self.page.locator("button:has-text('Apply Code')").click()
        self.page.wait_for_load_state("domcontentloaded")

    # ---- the control is there ----------------------------------------------

    def test_the_discount_select_is_rendered(self):
        expect(self._select()).to_be_visible()

    def test_the_code_is_offered_as_an_option(self):
        assert_page_has_text(self.page, "UITESTFREE100")

    def test_no_discount_is_the_starting_selection(self):
        """The fixture school has no code, so nothing must look applied."""
        expect(self._select()).to_have_value("")

    # ---- applying it -------------------------------------------------------

    def test_applying_a_code_attaches_it(self):
        self._select().select_option(str(self.code.pk))
        self._apply()

        self.sub.refresh_from_db()
        assert self.sub.discount_code_id == self.code.pk

    def test_applying_a_code_is_confirmed_on_the_page(self):
        self._select().select_option(str(self.code.pk))
        self._apply()

        assert_page_has_text(self.page, "applied to")

    def test_the_applied_code_comes_back_selected(self):
        """A reload has to show the deal that is in force, not a blank box —
        that is what made the old Django-admin round trip so easy to get wrong.
        """
        self._select().select_option(str(self.code.pk))
        self._apply()
        self._open()

        expect(self._select()).to_have_value(str(self.code.pk))

    def test_the_details_card_shows_the_percentage(self):
        self._select().select_option(str(self.code.pk))
        self._apply()

        assert_page_has_text(self.page, "UITESTFREE100 (100%)")

    # ---- clearing it -------------------------------------------------------

    def test_choosing_no_discount_clears_the_code(self):
        self.sub.discount_code = self.code
        self.sub.save(update_fields=["discount_code"])
        self._open()

        self._select().select_option("")
        self._apply()

        self.sub.refresh_from_db()
        assert self.sub.discount_code_id is None
        assert_page_has_text(self.page, "Discount code removed.")
