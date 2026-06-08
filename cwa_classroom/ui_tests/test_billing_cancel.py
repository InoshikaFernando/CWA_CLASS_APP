"""
UI tests for individual/student subscription cancellation (CPP-324).

Covers the parent/student billing page:
  - Active subscriber sees a Cancel Subscription button, confirms via the
    danger modal, and the page then shows the "will cancel on …" state.
  - No Cancel button when there is no active subscription.
  - No Cancel button when the subscription is already set to cancel.

The cancel view calls Stripe; since live_server runs in-process we monkeypatch
``billing.stripe_service.cancel_subscription`` to a no-op for the happy path.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login, _RUN_ID


def _make_subscription(user, *, status="active", stripe_sub_id="sub_ui_test",
                       cancel_at_period_end=False):
    from billing.models import Package, Subscription

    pkg = Package.objects.create(
        name=f"Basic {_RUN_ID}", price=Decimal("19.90"),
        class_limit=2, is_active=True,
    )
    sub, _ = Subscription.objects.update_or_create(
        user=user,
        defaults={
            "package": pkg,
            "status": status,
            "stripe_subscription_id": stripe_sub_id,
            "stripe_customer_id": "cus_ui_test",
            "current_period_end": timezone.now() + timedelta(days=20),
            "cancel_at_period_end": cancel_at_period_end,
        },
    )
    return sub


@pytest.mark.django_db(transaction=True)
def test_parent_cancels_subscription(page: Page, live_server, parent_with_child, monkeypatch):
    """Active subscriber clicks Cancel → confirms → page shows 'will cancel on' state."""
    from billing.models import Subscription

    monkeypatch.setattr("billing.stripe_service.cancel_subscription", lambda *a, **k: None)
    _make_subscription(parent_with_child, stripe_sub_id="sub_ui_cancel")

    do_login(page, str(live_server), parent_with_child)
    page.goto(f"{live_server}/parent/billing/")
    page.wait_for_load_state("networkidle")

    # The cancel trigger is visible for an active subscription.
    trigger = page.locator("#cancel-subscription-form button")
    expect(trigger).to_be_visible()
    trigger.click()

    # Danger confirm modal opens; click its confirm button (bound to confirmText).
    confirm_btn = page.locator('button[x-text="confirmText"]')
    expect(confirm_btn).to_be_visible()
    confirm_btn.click()

    # After the POST + redirect, the page reflects the cancelling state.
    page.wait_for_load_state("networkidle")
    expect(page.locator("text=Subscription will cancel on")).to_be_visible()

    sub = Subscription.objects.get(user=parent_with_child)
    assert sub.cancel_at_period_end is True
    assert sub.cancelled_at is not None


@pytest.mark.django_db(transaction=True)
def test_cancel_button_hidden_when_no_active_sub(page: Page, live_server, parent_with_child):
    """With no subscription, the billing page shows no Cancel button."""
    do_login(page, str(live_server), parent_with_child)
    page.goto(f"{live_server}/parent/billing/")
    page.wait_for_load_state("networkidle")

    expect(page.locator("text=No active subscription")).to_be_visible()
    expect(page.locator("#cancel-subscription-form")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_cancel_button_hidden_when_already_cancelling(page: Page, live_server, parent_with_child):
    """A subscription already set to cancel shows the amber note, not the button."""
    _make_subscription(parent_with_child, cancel_at_period_end=True)

    do_login(page, str(live_server), parent_with_child)
    page.goto(f"{live_server}/parent/billing/")
    page.wait_for_load_state("networkidle")

    expect(page.locator("text=Subscription will cancel on")).to_be_visible()
    expect(page.locator("#cancel-subscription-form")).to_have_count(0)
