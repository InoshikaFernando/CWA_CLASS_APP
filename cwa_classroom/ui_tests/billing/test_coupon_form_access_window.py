"""Playwright UI test — building a timed free promotion from the coupon form.

The unit tests prove the view stores what it is posted. What they cannot prove
is the thing that was actually broken: the field was on the page, but hidden for
this code type, so nobody could post it. A form test that posts the field
directly would have passed against the broken form.

So this drives the page the way a person does — pick Student (Billing), tick
Student Basic, and check the Access Duration field is *there to fill in*.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import _RUN_ID, do_login

# CI selects this file by its package, ui_tests/billing/, not by a marker.

CREATE_URL = '/admin-dashboard/billing/coupon-codes/create/'


@pytest.fixture
def coupon_superuser(db):
    from accounts.models import CustomUser

    from ..conftest import TEST_PASSWORD

    user = CustomUser.objects.create_superuser(
        username=f'coupon_root_{_RUN_ID}',
        email=f'coupon_root_{_RUN_ID}@test.local',
        password=TEST_PASSWORD,
    )
    user.profile_completed = True
    user.must_change_password = False
    user.save(update_fields=['profile_completed', 'must_change_password'])
    yield user
    user.delete()


class TestTheFormOffersADurationForABillingCode:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, coupon_superuser):
        self.page = page
        self.live_server = live_server
        do_login(page, live_server.url, coupon_superuser)
        page.goto(f'{live_server.url}{CREATE_URL}')
        page.wait_for_load_state('domcontentloaded')

    def _pick(self, target):
        self.page.locator(f'input[name="target_type"][value="{target}"]').check()
        self.page.wait_for_timeout(200)

    def test_student_billing_shows_both_the_tier_and_the_duration(self):
        """The combination that could not be built: they must co-exist."""
        self._pick('student_discount')

        expect(self.page.locator('#grants_student_basic')).to_be_visible()
        expect(self.page.locator('#grant_days')).to_be_visible()

    def test_a_promo_code_keeps_its_duration_too(self):
        self._pick('student_promo')
        expect(self.page.locator('#grant_days')).to_be_visible()

    def test_an_institute_code_has_neither(self):
        """Neither field means anything for an institute plan."""
        self._pick('institute')

        expect(self.page.locator('#grant_days')).not_to_be_visible()
        expect(self.page.locator('#grants_student_basic')).not_to_be_visible()

    def test_ticking_the_tier_without_a_duration_warns_on_the_page(self):
        """Before submitting, not after — a permanent free tier is legal but
        almost never what somebody ticking this actually means."""
        self._pick('student_discount')
        self.page.locator('#grants_student_basic').check()
        self.page.wait_for_timeout(200)

        expect(self.page.locator('#duration_needed_for_basic')).to_be_visible()

    def test_the_warning_clears_once_a_duration_is_typed(self):
        self._pick('student_discount')
        self.page.locator('#grants_student_basic').check()
        self.page.locator('#grant_days').fill('14')
        self.page.wait_for_timeout(200)

        expect(self.page.locator('#duration_needed_for_basic')
               ).not_to_be_visible()

    def test_the_tier_stays_locked_unless_the_code_is_free(self):
        """Unchanged behaviour, re-checked because the same JS now does more."""
        self._pick('student_discount')
        self.page.locator('#discount_percent').fill('50')
        self.page.dispatch_event('#discount_percent', 'change')
        self.page.wait_for_timeout(200)

        expect(self.page.locator('#grants_student_basic')).to_be_disabled()


class TestBuildingTheMHMCodeEndToEnd:

    def test_filling_the_form_in_produces_a_14_day_no_ai_free_code(
            self, live_server, page, coupon_superuser, db):
        from billing.models import DiscountCode

        code_name = f'MHMUI{_RUN_ID}'.upper()

        do_login(page, live_server.url, coupon_superuser)
        page.goto(f'{live_server.url}{CREATE_URL}')
        page.wait_for_load_state('domcontentloaded')

        page.locator('input[name="target_type"][value="student_discount"]').check()
        page.locator('input[name="code"]').fill(code_name)
        page.locator('#discount_percent').fill('100')
        page.dispatch_event('#discount_percent', 'change')
        page.locator('#grants_student_basic').check()
        page.locator('#grant_days').fill('14')
        page.locator('input[name="max_uses"]').fill('200')
        page.get_by_role('button', name='Create Code').click()
        page.wait_for_load_state('domcontentloaded')

        created = DiscountCode.objects.get(code=code_name)
        assert created.discount_percent == 100
        assert created.grant_days == 14, (
            'the window was dropped between the form and the database')
        assert created.grants_student_basic is True
        assert created.max_uses == 200

        created.delete()
