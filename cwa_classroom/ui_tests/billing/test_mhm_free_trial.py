"""Playwright UI test — the two weeks, and the morning they end.

The unit suite (``billing/tests_mhm_free_trial.py``) proves the rules. Three
things about this promotion can only be proved in a browser, and each of them is
what the student or their parent actually experiences:

* **No card form.** "No card details" is a promise made to a parent before their
  child signs up. A queryset assertion cannot tell you whether a card field is
  on the screen; only rendering the page can. Nothing here is allowed to reach
  Stripe, so a card field appearing is the failure.
* **The wall is a wall.** On day fifteen the student opens the app the way they
  did yesterday and has to be stopped — from the page they were on, by the
  middleware, not by a link they chose to click.
* **It reads as an ending, not a fault.** They see "your promotion has ended"
  and a price, rather than "your trial expired" or a payment error for a card
  they never gave.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from ui_tests.conftest import _RUN_ID, do_login

# No pytestmark: the markers here name feature areas for a local subset run,
# and `invoice` (what the rest of this package uses) would be a lie. CI selects
# this file by its package, ui_tests/billing/, not by a marker.

CODE = f'MHM2WEEKS{_RUN_ID}'.upper()


@pytest.fixture
def mhm_code(db):
    """The promotion, minted exactly as the command mints it."""
    from billing.models import DiscountCode

    code = DiscountCode.objects.create(
        code=CODE, discount_percent=100, grant_days=14,
        grants_student_basic=True, is_active=True,
    )
    yield code
    code.delete()


@pytest.fixture
def paid_package(db):
    """The plan they are asked to move onto when the two weeks are up."""
    from billing.models import Package

    package = Package.objects.create(
        name=f'Wizard {_RUN_ID}', price=19.90, class_limit=0,
        stripe_price_id='price_ui_mhm', is_active=True, is_default=True,
    )
    yield package
    package.delete()


def _grant(student, package, code, days_left):
    """Put *student* on the promotion with *days_left* remaining.

    Negative days mean the window has already closed — which is the state the
    student wakes up in on day fifteen, with nothing having run overnight to
    tell them.
    """
    from billing.entitlements import sync_student_modules
    from billing.models import Subscription

    sub = Subscription.objects.create(
        user=student, package=package,
        status=Subscription.STATUS_ACTIVE,
        discount_code=code, discount_percent_snapshot=100,
        trial_end=timezone.now() + timedelta(days=days_left),
    )
    sync_student_modules(sub)
    return sub


class TestTheFreeFortnight:
    """Day one: they work, and nobody asks them for a card."""

    def test_a_student_on_the_promotion_gets_into_the_app(
            self, live_server, page, enrolled_student, paid_package, mhm_code):
        _grant(enrolled_student, paid_package, mhm_code, days_left=13)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('domcontentloaded')

        assert '/accounts/trial-expired/' not in page.url, (
            'a student inside the free window was sent to the payment wall')

    def test_no_card_field_is_anywhere_on_the_page(
            self, live_server, page, enrolled_student, paid_package, mhm_code):
        """The promise the parent was given, checked against what renders.

        Stripe's own fields arrive in an iframe, so both are looked for: a card
        input of our own, and any Stripe frame at all.
        """
        _grant(enrolled_student, paid_package, mhm_code, days_left=13)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('domcontentloaded')

        card_fields = page.locator(
            'input[name*="card" i], input[autocomplete="cc-number"], '
            'input[placeholder*="card number" i], #card-element')
        expect(card_fields).to_have_count(0)
        assert not any('stripe' in (frame.url or '').lower()
                       for frame in page.frames)


class TestTheMorningItEnds:
    """Day fifteen: stopped where they stand, and told why."""

    def test_the_student_is_bounced_off_the_app_to_the_wall(
            self, live_server, page, enrolled_student, paid_package, mhm_code):
        _grant(enrolled_student, paid_package, mhm_code, days_left=-1)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('domcontentloaded')

        assert '/accounts/trial-expired/' in page.url, (
            f'expected the payment wall, landed on {page.url}')

    def test_it_says_the_promotion_ended_and_shows_what_it_costs(
            self, live_server, page, enrolled_student, paid_package, mhm_code):
        _grant(enrolled_student, paid_package, mhm_code, days_left=-1)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('domcontentloaded')

        expect(page.get_by_text('Your promotion has ended')).to_be_visible()
        expect(page.get_by_text('19.90')).to_be_visible()

    def test_the_way_to_pay_is_on_the_wall_itself(
            self, live_server, page, enrolled_student, paid_package, mhm_code):
        """Being stopped is only half of it — they have to be able to carry on."""
        _grant(enrolled_student, paid_package, mhm_code, days_left=-1)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('domcontentloaded')

        checkout_link = page.locator(
            f'a[href*="/billing/checkout/{paid_package.id}/"]')
        expect(checkout_link.first).to_be_visible()

    def test_an_upgraded_student_is_let_straight_back_in(
            self, live_server, page, enrolled_student, paid_package, mhm_code):
        """After paying, the wall is gone and so is the free edition."""
        from billing.entitlements import (
            active_student_modules, sync_student_modules,
        )
        from billing.models import StudentModule, Subscription

        sub = _grant(enrolled_student, paid_package, mhm_code, days_left=-1)
        assert StudentModule.MODULE_BASIC in active_student_modules(
            enrolled_student)

        # What the webhook does when their payment lands.
        sub.stripe_subscription_id = 'sub_ui_paid'
        sub.status = Subscription.STATUS_ACTIVE
        sub.trial_end = None
        sub.save()
        sync_student_modules(sub)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('domcontentloaded')

        assert '/accounts/trial-expired/' not in page.url
        modules = active_student_modules(enrolled_student)
        assert StudentModule.MODULE_BASIC not in modules
        assert StudentModule.MODULE_AI_GRADING in modules
