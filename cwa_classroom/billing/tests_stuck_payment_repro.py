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
