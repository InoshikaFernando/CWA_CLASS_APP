"""One person, one Stripe customer.

``get_or_create_customer`` persists the customer id onto the Subscription — but
a school student has no Subscription until checkout succeeds, so a failed
attempt had nowhere to put it and the next attempt made another customer. One
student retrying a broken checkout on 2026-09-07 did that eleven times.

Duplicates matter beyond tidiness: a Stripe customer is currency-locked once it
carries a subscription, so several of them is how one person ends up with two
currencies and a checkout that dies on "You cannot combine currencies on a
single customer".
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, call, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from billing.models import Package, Subscription
from billing.stripe_service import get_or_create_customer

CustomUser = get_user_model()


def _cust(cid, user_id, created=1000):
    return {'id': cid, 'created': created, 'metadata': {'user_id': str(user_id)}}


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class GetOrCreateCustomerIsIdempotentTest(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            'kiyali', 'kassapa+kiyali@gmail.com', 'x',
            first_name='Kiyali', last_name='S',
        )

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_existing_customer_is_reused_when_there_is_no_subscription(
            self, mock_list, mock_create):
        """The regression: no local row to persist to must not mean a new customer."""
        mock_list.return_value = {'data': [_cust('cus_first', self.user.id)]}
        cid = get_or_create_customer(user=self.user)
        self.assertEqual(cid, 'cus_first')
        mock_create.assert_not_called()

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_repeated_failed_checkouts_converge_on_one_customer(
            self, mock_list, mock_create):
        """Eleven retries, one customer — the actual production shape."""
        mock_create.return_value = MagicMock(id='cus_made')
        mock_list.return_value = {'data': []}
        first = get_or_create_customer(user=self.user)

        # Every later attempt now finds the one just made.
        mock_list.return_value = {'data': [_cust(first, self.user.id)]}
        for _ in range(10):
            self.assertEqual(get_or_create_customer(user=self.user), first)
        self.assertEqual(mock_create.call_count, 1)

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_oldest_is_chosen_so_retries_do_not_walk_forward(
            self, mock_list, mock_create):
        mock_list.return_value = {'data': [
            _cust('cus_new', self.user.id, created=3000),
            _cust('cus_old', self.user.id, created=1000),
            _cust('cus_mid', self.user.id, created=2000),
        ]}
        self.assertEqual(get_or_create_customer(user=self.user), 'cus_old')
        mock_create.assert_not_called()

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_another_users_customer_on_the_same_email_is_not_stolen(
            self, mock_list, mock_create):
        """Plus-addressed families share an inbox; metadata decides, not email."""
        mock_create.return_value = MagicMock(id='cus_mine')
        mock_list.return_value = {'data': [_cust('cus_sibling', 9999)]}
        self.assertEqual(get_or_create_customer(user=self.user), 'cus_mine')
        mock_create.assert_called_once()

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_saved_id_wins_without_asking_stripe(self, mock_list, mock_create):
        pkg = Package.objects.create(
            name='Wizard', price=Decimal('19.90'),
            stripe_price_id='price_x', class_limit=1)
        Subscription.objects.create(
            user=self.user, package=pkg, stripe_customer_id='cus_saved')
        self.assertEqual(get_or_create_customer(user=self.user), 'cus_saved')
        mock_list.assert_not_called()
        mock_create.assert_not_called()

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_found_id_is_persisted_when_a_subscription_exists(
            self, mock_list, mock_create):
        pkg = Package.objects.create(
            name='Wizard', price=Decimal('19.90'),
            stripe_price_id='price_x', class_limit=1)
        sub = Subscription.objects.create(user=self.user, package=pkg)
        mock_list.return_value = {'data': [_cust('cus_found', self.user.id)]}
        get_or_create_customer(user=self.user)
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_found')

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list', side_effect=Exception('Stripe list down'))
    def test_lookup_failure_falls_back_to_creating(self, _mock_list, mock_create):
        """A dedupe nicety must never block a payment."""
        mock_create.return_value = MagicMock(id='cus_fallback')
        self.assertEqual(get_or_create_customer(user=self.user), 'cus_fallback')

    @patch('stripe.Customer.create')
    @patch('stripe.Customer.list')
    def test_user_without_email_skips_the_lookup(self, mock_list, mock_create):
        self.user.email = None
        self.user.save(update_fields=['email'])
        mock_create.return_value = MagicMock(id='cus_noemail')
        self.assertEqual(get_or_create_customer(user=self.user), 'cus_noemail')
        mock_list.assert_not_called()


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class DedupeStripeCustomersCommandTest(TestCase):
    """Cleaning up the duplicates already in Stripe."""

    def setUp(self):
        self.user = CustomUser.objects.create_user('kiyali', 'k@test.com', 'x')
        self.customers = [
            _cust('cus_keep', self.user.id, created=1000),
            _cust('cus_dupe1', self.user.id, created=2000),
            _cust('cus_dupe2', self.user.id, created=3000),
        ]

    def _run(self, empty=True, **kw):
        out, err = StringIO(), StringIO()
        listing = MagicMock()
        listing.auto_paging_iter.return_value = iter(self.customers)
        empty_page = MagicMock(data=[])
        full_page = MagicMock(data=[{'id': 'x'}])
        page = empty_page if empty else full_page
        with patch('stripe.Customer.list', return_value=listing), \
             patch('stripe.Subscription.list', return_value=page), \
             patch('stripe.Charge.list', return_value=page), \
             patch('stripe.Invoice.list', return_value=page), \
             patch('stripe.Customer.delete') as mock_delete:
            call_command('dedupe_stripe_customers', stdout=out, stderr=err, **kw)
        return out.getvalue(), err.getvalue(), mock_delete

    def test_report_only_by_default(self):
        out, _, mock_delete = self._run()
        self.assertIn('would delete cus_dupe1', out)
        self.assertIn('Report only', out)
        mock_delete.assert_not_called()

    def test_delete_removes_empty_duplicates_and_keeps_the_oldest(self):
        out, _, mock_delete = self._run(delete=True)
        self.assertIn('keeping oldest cus_keep', out)
        self.assertEqual(
            sorted(c.args[0] for c in mock_delete.call_args_list),
            ['cus_dupe1', 'cus_dupe2'],
        )
        self.assertIn('Deleted 2', out)

    def test_a_duplicate_with_history_is_never_deleted(self):
        """Anything with money attached is reported, not removed."""
        out, _, mock_delete = self._run(empty=False, delete=True)
        self.assertIn('KEEP', out)
        mock_delete.assert_not_called()

    def test_locally_recorded_customer_is_never_deleted(self):
        pkg = Package.objects.create(
            name='Wizard', price=Decimal('19.90'),
            stripe_price_id='price_x', class_limit=1)
        Subscription.objects.create(
            user=self.user, package=pkg, stripe_customer_id='cus_dupe1')
        out, _, mock_delete = self._run(delete=True)
        self.assertIn('recorded in our database', out)
        self.assertEqual(
            [c.args[0] for c in mock_delete.call_args_list], ['cus_dupe2'])

    def test_no_duplicates_reports_clean(self):
        self.customers = [_cust('cus_only', self.user.id)]
        out, _, mock_delete = self._run(delete=True)
        self.assertIn('No user has more than one', out)
        mock_delete.assert_not_called()

    def test_user_filter_limits_the_scan(self):
        other = CustomUser.objects.create_user('other', 'o@test.com', 'x')
        self.customers.append(_cust('cus_other1', other.id))
        self.customers.append(_cust('cus_other2', other.id))
        out, _, _ = self._run(user=self.user.id)
        self.assertIn('cus_dupe1', out)
        self.assertNotIn('cus_other', out)
