"""
Persisting stripe_customer_id (forward-fix) + the one-time backfill command.

Regression cover for the bug where checkout/webhook saved the subscription id
but never the customer id, leaving the billing portal unable to open and
spawning duplicate Stripe customers on re-checkout.
"""
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.models import CustomUser, Role, UserRole
from classroom.models import School
from billing.models import Package, Subscription, SchoolSubscription, InstitutePlan
from billing.webhook_handlers import handle_checkout_completed, handle_subscription_updated


def _student(username='cid_stu'):
    u = CustomUser.objects.create_user(username, email=f'{username}@t.local', password='x')
    role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.create(user=u, role=role)
    return u


class WebhookPersistsCustomerIdTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(name='Student', price=19.90, stripe_price_id='price_cid')

    @patch('stripe.Subscription.retrieve')
    def test_checkout_saves_customer_id_for_new_school_student(self, mock_ret):
        # retrieve is used for trial detection; make it inert (no customer here)
        mock_ret.return_value = type('S', (), {'status': 'active', 'customer': None})()
        stu = _student('cid_new')
        event = {'object': {
            'metadata': {'type': 'school_student', 'user_id': str(stu.id), 'package_id': str(self.pkg.id)},
            'subscription': 'sub_new', 'customer': 'cus_from_session',
        }}
        handle_checkout_completed(event)
        sub = Subscription.objects.get(user=stu)
        self.assertEqual(sub.stripe_customer_id, 'cus_from_session')
        self.assertEqual(sub.stripe_subscription_id, 'sub_new')

    def test_subscription_updated_saves_customer_id(self):
        stu = _student('cid_upd')
        sub = Subscription.objects.create(
            user=stu, package=self.pkg, status=Subscription.STATUS_TRIALING,
            stripe_subscription_id='sub_upd',
        )
        event = {'object': {
            'id': 'sub_upd', 'status': 'active', 'customer': 'cus_from_update',
            'metadata': {'type': 'individual', 'user_id': str(stu.id)},
            'cancel_at_period_end': False,
        }}
        handle_subscription_updated(event)
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_from_update')
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)

    def test_update_without_customer_does_not_blank_existing(self):
        stu = _student('cid_keep')
        sub = Subscription.objects.create(
            user=stu, package=self.pkg, status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id='sub_keep', stripe_customer_id='cus_existing',
        )
        event = {'object': {
            'id': 'sub_keep', 'status': 'past_due',
            'metadata': {'type': 'individual', 'user_id': str(stu.id)},
            'cancel_at_period_end': False,
        }}  # no 'customer' key
        handle_subscription_updated(event)
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_existing')   # preserved
        self.assertEqual(sub.status, Subscription.STATUS_PAST_DUE)  # status still synced


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class BackfillCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(name='P', price=1, stripe_price_id='pp')

    def _sub(self, username, sub_id='sub_bf', cust=''):
        u = CustomUser.objects.create_user(username, email=f'{username}@t.local', password='x')
        return Subscription.objects.create(
            user=u, package=self.pkg, status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id=sub_id, stripe_customer_id=cust,
        )

    @patch('stripe.Subscription.retrieve')
    def test_backfills_customer_id_from_stripe(self, mock_ret):
        sub = self._sub('bf1')
        mock_ret.return_value = type('S', (), {'customer': 'cus_bf1'})()
        call_command('backfill_stripe_customer_ids')
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_bf1')

    @patch('stripe.Subscription.retrieve')
    def test_dry_run_writes_nothing(self, mock_ret):
        sub = self._sub('bf2')
        mock_ret.return_value = type('S', (), {'customer': 'cus_bf2'})()
        call_command('backfill_stripe_customer_ids', '--dry-run')
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, '')

    @patch('stripe.Subscription.retrieve')
    def test_leaves_already_populated_untouched(self, mock_ret):
        self._sub('bf3', cust='cus_already')
        call_command('backfill_stripe_customer_ids')
        mock_ret.assert_not_called()  # excluded by the empty-customer filter
