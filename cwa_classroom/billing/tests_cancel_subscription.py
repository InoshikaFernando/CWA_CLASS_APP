"""
Unit tests for IndividualCancelSubscriptionView (CPP-324).

Covers the student/individual self-service subscription cancellation flow:
happy path, audit logging, error handling, login gating, and isolation
(cancelling one user's subscription never touches another's).
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from audit.models import AuditLog
from billing.models import Package, Subscription


def _create_package(name='Pro', price=Decimal('19.90')):
    return Package.objects.create(
        name=name, price=price, stripe_price_id='price_pkg_test', is_active=True,
    )


def _create_user_with_subscription(username, stripe_sub_id='sub_stripe_123',
                                    status=Subscription.STATUS_ACTIVE,
                                    cancel_at_period_end=False):
    user = CustomUser.objects.create_user(
        username=username, password='testpass123', email=f'{username}@test.com',
    )
    sub = Subscription.objects.create(
        user=user,
        package=_create_package(name=f'Pkg-{username}'),
        stripe_subscription_id=stripe_sub_id,
        stripe_customer_id='cus_test',
        status=status,
        current_period_end=timezone.now() + timezone.timedelta(days=20),
        cancel_at_period_end=cancel_at_period_end,
    )
    return user, sub


class IndividualCancelSubscriptionViewTest(TestCase):
    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_sets_cancel_at_period_end(self, mock_cancel):
        user, sub = _create_user_with_subscription('cancel_ok')
        self.client.login(username='cancel_ok', password='testpass123')

        resp = self.client.post(reverse('cancel_subscription'))

        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_called_once_with('sub_stripe_123', at_period_end=True)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        self.assertIsNotNone(sub.cancelled_at)

    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_logs_audit_event(self, mock_cancel):
        user, sub = _create_user_with_subscription('cancel_audit')
        self.client.login(username='cancel_audit', password='testpass123')

        self.client.post(reverse('cancel_subscription'))

        self.assertTrue(
            AuditLog.objects.filter(
                user=user, category='billing', action='subscription_cancelled',
            ).exists()
        )

    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_no_active_subscription_errors(self, mock_cancel):
        # User exists but has no Subscription at all.
        CustomUser.objects.create_user(
            username='cancel_nosub', password='testpass123', email='ns@test.com',
        )
        self.client.login(username='cancel_nosub', password='testpass123')

        resp = self.client.post(reverse('cancel_subscription'))

        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_not_called()

    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_no_stripe_id_errors(self, mock_cancel):
        # Subscription exists but was never linked to Stripe.
        _create_user_with_subscription('cancel_nostripe', stripe_sub_id='')
        self.client.login(username='cancel_nostripe', password='testpass123')

        resp = self.client.post(reverse('cancel_subscription'))

        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_not_called()

    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_already_cancelling_is_noop(self, mock_cancel):
        _create_user_with_subscription('cancel_already', cancel_at_period_end=True)
        self.client.login(username='cancel_already', password='testpass123')

        resp = self.client.post(reverse('cancel_subscription'))

        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_not_called()

    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_stripe_error_handled(self, mock_cancel):
        import stripe as stripe_mod
        mock_cancel.side_effect = stripe_mod.error.StripeError('cancel fail')
        user, sub = _create_user_with_subscription('cancel_err')
        self.client.login(username='cancel_err', password='testpass123')

        resp = self.client.post(reverse('cancel_subscription'))

        self.assertEqual(resp.status_code, 302)
        sub.refresh_from_db()
        # On Stripe failure the local state must NOT flip to cancelling.
        self.assertFalse(sub.cancel_at_period_end)

    @patch('billing.stripe_service.cancel_subscription')
    def test_individual_cancel_only_affects_own_subscription(self, mock_cancel):
        user_a, sub_a = _create_user_with_subscription('cancel_a', stripe_sub_id='sub_a')
        user_b, sub_b = _create_user_with_subscription('cancel_b', stripe_sub_id='sub_b')

        self.client.login(username='cancel_a', password='testpass123')
        self.client.post(reverse('cancel_subscription'))

        sub_a.refresh_from_db()
        sub_b.refresh_from_db()
        self.assertTrue(sub_a.cancel_at_period_end)
        self.assertFalse(sub_b.cancel_at_period_end)
        mock_cancel.assert_called_once_with('sub_a', at_period_end=True)

    def test_individual_cancel_requires_login(self):
        resp = self.client.post(reverse('cancel_subscription'))
        # LoginRequiredMixin redirects anonymous users to the login page.
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)
