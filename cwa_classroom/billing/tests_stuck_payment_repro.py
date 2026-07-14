"""
Reproduction: a paid Stripe subscription that never reaches the local DB leaves
an individual student walled off behind 'trial expired', even though Stripe holds
an active subscription.

Proves the mechanism precisely (not a guess):
  * access is gated ONLY on the local Subscription.status (TrialExpiryMiddleware),
  * a *processed* activation webhook ALWAYS flips an existing individual
    subscriber to active — via BOTH checkout.session.completed AND
    customer.subscription.created/updated,
  * therefore the only way she stays gated after paying is that NO webhook was
    processed (transport/verification failure), not a handler-logic bug.
"""
import pytest
from datetime import timedelta
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import Package, Subscription
from billing.webhook_handlers import (
    handle_checkout_completed,
    handle_subscription_updated,
)
from cwa_classroom.middleware import TrialExpiryMiddleware


def _individual_student_with_expired_sub():
    role, _ = Role.objects.get_or_create(
        name=Role.INDIVIDUAL_STUDENT, defaults={'display_name': 'Individual Student'})
    user = CustomUser.objects.create_user(
        username='sanduli', email='ratnayakehimali+sanduli@yahoo.com',
        first_name='Sanduli', last_name='Herath', password='x')
    UserRole.objects.get_or_create(user=user, role=role)
    pkg = Package.objects.create(name='Student Subscription (Wizard)', price=19.90,
                                 is_active=True, stripe_price_id='price_wizard')
    # Trial ended → middleware auto-flips TRIALING to EXPIRED; model the post-flip state.
    sub = Subscription.objects.create(
        user=user, package=pkg, status=Subscription.STATUS_EXPIRED,
        trial_end=timezone.now() - timedelta(days=1))
    return user, pkg, sub


@pytest.mark.django_db
def test_paid_but_no_webhook_stays_gated_then_webhook_unblocks():
    user, pkg, sub = _individual_student_with_expired_sub()

    # 1. BEFORE any webhook: this is the prod symptom. Stripe has her money, but
    #    the local row is expired, so the middleware gate treats her as expired.
    assert TrialExpiryMiddleware._is_trial_expired(sub) is True

    # 2. A processed customer.subscription.created/updated event activates her.
    handle_subscription_updated({'object': {
        'id': 'sub_1Tt3Qq',
        'status': 'active',
        'metadata': {'type': 'individual', 'user_id': str(user.id), 'package_id': str(pkg.id)},
        'cancel_at_period_end': False,
        'customer': 'cus_Usp1j6',
    }})
    sub.refresh_from_db()
    assert sub.status == Subscription.STATUS_ACTIVE
    assert sub.stripe_subscription_id == 'sub_1Tt3Qq'
    assert TrialExpiryMiddleware._is_trial_expired(sub) is False


@pytest.mark.django_db
def test_incomplete_status_is_mapped_not_stored_raw():
    """A subscription.created (status=incomplete) event must map to a gated
    local status, never store the raw Stripe value 'incomplete'."""
    user, pkg, sub = _individual_student_with_expired_sub()
    handle_subscription_updated({'object': {
        'id': 'sub_1Tt3Qq', 'status': 'incomplete',
        'metadata': {'type': 'individual', 'user_id': str(user.id)},
        'cancel_at_period_end': False, 'customer': 'cus_x',
    }})
    sub.refresh_from_db()
    assert sub.status == Subscription.STATUS_PAST_DUE      # mapped, gated
    assert sub.status != 'incomplete'                       # never raw


@pytest.mark.django_db
def test_out_of_order_incomplete_does_not_downgrade_active():
    """The reported bug: a stale 'incomplete' event arriving AFTER activation
    must not knock an active subscriber back offline."""
    user, pkg, sub = _individual_student_with_expired_sub()
    # 1. activation lands
    handle_subscription_updated({'object': {
        'id': 'sub_1Tt3Qq', 'status': 'active',
        'metadata': {'type': 'individual', 'user_id': str(user.id)},
        'cancel_at_period_end': False, 'customer': 'cus_x',
    }})
    sub.refresh_from_db()
    assert sub.status == Subscription.STATUS_ACTIVE
    # 2. stale created(incomplete) arrives out of order
    handle_subscription_updated({'object': {
        'id': 'sub_1Tt3Qq', 'status': 'incomplete',
        'metadata': {'type': 'individual', 'user_id': str(user.id)},
        'cancel_at_period_end': False, 'customer': 'cus_x',
    }})
    sub.refresh_from_db()
    assert sub.status == Subscription.STATUS_ACTIVE         # stays active
    assert TrialExpiryMiddleware._is_trial_expired(sub) is False


@pytest.mark.django_db
def test_success_page_creates_subscription_when_missing(monkeypatch):
    """Success-page safety net must create a Subscription row for a paid user
    who has none yet, instead of silently returning."""
    import types
    from billing.views import CheckoutSuccessView
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'})
    user = CustomUser.objects.create_user(username='sc', email='sc@school.test', password='x')
    UserRole.objects.get_or_create(user=user, role=role)
    pkg = Package.objects.create(name='Wizard', price=19.90, is_active=True, stripe_price_id='p')
    assert not Subscription.objects.filter(user=user).exists()

    fake_session = types.SimpleNamespace(
        payment_status='paid', subscription='sub_new', customer='cus_new',
        metadata={'package_id': str(pkg.id)})
    monkeypatch.setattr('stripe.checkout.Session.retrieve', lambda _sid: fake_session)

    CheckoutSuccessView._activate_from_session(user, 'cs_test')
    sub = Subscription.objects.get(user=user)
    assert sub.status == Subscription.STATUS_ACTIVE
    assert sub.stripe_subscription_id == 'sub_new'


@pytest.mark.django_db
def test_checkout_completed_also_activates_existing_individual():
    user, pkg, sub = _individual_student_with_expired_sub()
    assert TrialExpiryMiddleware._is_trial_expired(sub) is True

    # checkout.session.completed with empty subscription id → skips the Stripe
    # API retrieve and takes the ACTIVE branch. (Independent second path.)
    handle_checkout_completed({'object': {
        'id': 'cs_test_1',
        'metadata': {'type': 'individual', 'user_id': str(user.id), 'package_id': str(pkg.id)},
        'subscription': '',
        'customer': 'cus_Usp1j6',
    }})
    sub.refresh_from_db()
    assert sub.status == Subscription.STATUS_ACTIVE
    assert TrialExpiryMiddleware._is_trial_expired(sub) is False
