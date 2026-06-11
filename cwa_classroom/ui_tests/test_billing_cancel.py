"""
UI tests for individual/student subscription cancellation (CPP-324).

Primary surface is the individual student's billing page (billing_history),
linked from the student sidebar. The parent billing page shares the same
cancel partial for parents who hold a personal subscription.

Covers:
  - Individual student: Cancel button → danger confirm modal → "will cancel
    on …" state, with the redirect landing back on /billing/history/.
  - No Cancel button when there is no active subscription.
  - No Cancel button when the subscription is already set to cancel.
  - Parent with a personal subscription cancels from the parent billing page.

The cancel view calls Stripe; since live_server runs in-process we monkeypatch
``billing.stripe_service.cancel_subscription`` to a no-op for happy paths.
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


def _confirm_cancel(page: Page):
    """Click the cancel trigger, then the modal's confirm button."""
    trigger = page.locator("#cancel-subscription-form button")
    expect(trigger).to_be_visible()
    trigger.click()

    confirm_btn = page.locator('button[x-text="confirmText"]')
    expect(confirm_btn).to_be_visible()
    confirm_btn.click()
    page.wait_for_load_state("networkidle")


@pytest.mark.django_db(transaction=True)
def test_individual_student_cancels_subscription(
    page: Page, live_server, individual_student_user, monkeypatch,
):
    """Individual student cancels from their billing page and lands back on it."""
    from billing.models import Subscription

    monkeypatch.setattr("billing.stripe_service.cancel_subscription", lambda *a, **k: None)
    _make_subscription(individual_student_user, stripe_sub_id="sub_ui_individual")

    do_login(page, str(live_server), individual_student_user)
    page.goto(f"{live_server}/billing/history/")
    page.wait_for_load_state("networkidle")

    _confirm_cancel(page)

    # Redirect lands back on the individual billing page, now in cancelling state.
    expect(page).to_have_url(f"{live_server}/billing/history/")
    expect(page.locator("text=Subscription will cancel on")).to_be_visible()
    expect(page.locator("#cancel-subscription-form")).to_have_count(0)

    sub = Subscription.objects.get(user=individual_student_user)
    assert sub.cancel_at_period_end is True
    assert sub.cancelled_at is not None


@pytest.mark.django_db(transaction=True)
def test_cancel_button_hidden_when_no_active_sub(
    page: Page, live_server, individual_student_user,
):
    """With no subscription, the billing page shows no Cancel button."""
    do_login(page, str(live_server), individual_student_user)
    page.goto(f"{live_server}/billing/history/")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#cancel-subscription-form")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_cancel_button_hidden_when_already_cancelling(
    page: Page, live_server, individual_student_user,
):
    """A subscription already set to cancel shows the amber note, not the button."""
    _make_subscription(individual_student_user, cancel_at_period_end=True)

    do_login(page, str(live_server), individual_student_user)
    page.goto(f"{live_server}/billing/history/")
    page.wait_for_load_state("networkidle")

    expect(page.locator("text=Subscription will cancel on")).to_be_visible()
    expect(page.locator("#cancel-subscription-form")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_parent_cancels_subscription_from_parent_billing(
    page: Page, live_server, parent_with_child, monkeypatch,
):
    """A parent holding a personal subscription cancels from the parent billing page."""
    from billing.models import Subscription

    monkeypatch.setattr("billing.stripe_service.cancel_subscription", lambda *a, **k: None)
    _make_subscription(parent_with_child, stripe_sub_id="sub_ui_parent")

    do_login(page, str(live_server), parent_with_child)
    page.goto(f"{live_server}/parent/billing/")
    page.wait_for_load_state("networkidle")

    _confirm_cancel(page)

    # Parent is redirected back to the parent billing page.
    expect(page).to_have_url(f"{live_server}/parent/billing/")
    expect(page.locator("text=Subscription will cancel on")).to_be_visible()

    sub = Subscription.objects.get(user=parent_with_child)
    assert sub.cancel_at_period_end is True
