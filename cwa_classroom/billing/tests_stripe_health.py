"""Checkout failures and broken Stripe prices must be visible in the app.

On 2026-09-07 an archived Stripe price broke the payment page for every school
student. The student saw "contact support"; the reason — *The price specified
is inactive* — existed only in a log file on the droplet, and took two weeks
and an SSH session to find while the student retried eleven times.

These cover both halves of not repeating that: the failure is recorded where a
super admin can read it, and the misconfiguration behind it is detected before
the next student hits it.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from billing.models import InstitutePlan, Package
from billing.stripe_health import (
    CHECKOUT_FAILED, get_checkout_failure_health, get_stripe_price_health,
    record_checkout_failure,
)

CustomUser = get_user_model()

INACTIVE_PRICE_ERROR = (
    'The price specified is inactive. This field only accepts active prices.'
)


class RecordCheckoutFailureTest(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user('payer', 'payer@test.com', 'x')
        self.pkg = Package.objects.create(
            name='Student Monthly', price=Decimal('19.90'),
            stripe_price_id='price_dead', class_limit=1,
        )

    def test_failure_is_recorded_with_the_stripe_message(self):
        record_checkout_failure(
            Exception(INACTIVE_PRICE_ERROR), user=self.user,
            package=self.pkg, flow='school_student_complete_profile',
        )
        ev = AuditLog.objects.get(action=CHECKOUT_FAILED)
        self.assertEqual(ev.user, self.user)
        self.assertEqual(ev.category, 'billing')
        self.assertEqual(ev.result, 'blocked')
        self.assertIn('inactive', ev.detail['error'])
        self.assertEqual(ev.detail['package'], 'Student Monthly')
        self.assertEqual(ev.detail['stripe_price_id'], 'price_dead')
        self.assertEqual(ev.detail['flow'], 'school_student_complete_profile')

    def test_recording_never_raises(self):
        """Monitoring must not turn a payment failure into a 500 on top of it."""
        with patch('audit.services.log_event', side_effect=Exception('audit down')):
            record_checkout_failure(Exception('boom'), user=self.user)  # no raise


class CheckoutFailureHealthTest(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            'kiyali', 'k@test.com', 'x', first_name='Kiyali', last_name='S')
        self.pkg = Package.objects.create(
            name='Student Monthly', price=Decimal('19.90'),
            stripe_price_id='price_dead', class_limit=1,
        )

    def _fail(self, n=1, user=None):
        for _ in range(n):
            record_checkout_failure(
                Exception(INACTIVE_PRICE_ERROR), user=user or self.user,
                package=self.pkg, flow='school_student_complete_profile',
            )

    def test_clean_when_nothing_failed(self):
        health = get_checkout_failure_health()
        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['count'], 0)
        self.assertEqual(health['rows'], [])

    def test_a_single_failure_is_a_warning_not_silence(self):
        self._fail()
        health = get_checkout_failure_health()
        self.assertEqual(health['status'], 'warning')
        self.assertEqual(health['count'], 1)
        self.assertEqual(health['users'], 1)

    def test_repeated_failures_are_critical(self):
        """Kiyali's real shape: one student, eleven attempts."""
        self._fail(11)
        health = get_checkout_failure_health()
        self.assertEqual(health['status'], 'critical')
        self.assertEqual(health['count'], 11)
        self.assertEqual(health['users'], 1)
        self.assertIn('could not pay', health['reasons'][0])

    def test_rows_carry_who_and_why(self):
        self._fail()
        row = get_checkout_failure_health()['rows'][0]
        self.assertEqual(row['username'], 'kiyali')
        self.assertEqual(row['name'], 'Kiyali S')
        self.assertEqual(row['package'], 'Student Monthly')
        self.assertIn('inactive', row['error'])

    def test_top_error_names_the_common_cause(self):
        self._fail(3)
        self.assertEqual(get_checkout_failure_health()['top_error'], INACTIVE_PRICE_ERROR)

    def test_second_student_escalates_to_critical(self):
        other = CustomUser.objects.create_user('other', 'o@test.com', 'x')
        self._fail(1)
        self._fail(1, user=other)
        health = get_checkout_failure_health()
        self.assertEqual(health['users'], 2)
        self.assertEqual(health['status'], 'critical')

    def test_old_failures_fall_out_of_the_window(self):
        self._fail()
        AuditLog.objects.update(created_at=timezone.now() - timedelta(days=30))
        self.assertEqual(get_checkout_failure_health(days=7)['count'], 0)

    def test_rows_are_capped_and_flagged_as_truncated(self):
        self._fail(25)
        health = get_checkout_failure_health(limit=20)
        self.assertEqual(health['count'], 25)
        self.assertEqual(len(health['rows']), 20)
        self.assertTrue(health['truncated'])


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class StripePriceHealthTest(TestCase):

    def setUp(self):
        cache.clear()
        self.pkg = Package.objects.create(
            name='Student Monthly', price=Decimal('19.90'),
            stripe_price_id='price_live', class_limit=1,
        )

    def tearDown(self):
        cache.clear()

    @patch('stripe.Price.retrieve')
    def test_active_price_is_healthy(self, mock_retrieve):
        mock_retrieve.return_value = {'active': True}
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['checked'], 1)
        self.assertEqual(health['broken'], [])

    @patch('stripe.Price.retrieve')
    def test_archived_price_is_critical_and_named(self, mock_retrieve):
        """The exact production failure, caught before a student hits it."""
        mock_retrieve.return_value = {'active': False}
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'critical')
        broken = health['broken'][0]
        self.assertEqual(broken['label'], 'Student Monthly')
        self.assertEqual(broken['price_id'], 'price_live')
        self.assertIn('Archived in Stripe', broken['problem'])

    @patch('stripe.Price.retrieve', side_effect=Exception('No such price'))
    def test_missing_price_is_reported(self, _mock):
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'critical')
        self.assertIn('No such price', health['broken'][0]['problem'])

    @patch('stripe.Price.retrieve')
    def test_paid_plan_with_no_price_id_is_reported(self, mock_retrieve):
        Package.objects.filter(pk=self.pkg.pk).update(stripe_price_id='')
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'critical')
        self.assertIn('No Stripe price id', health['broken'][0]['problem'])
        mock_retrieve.assert_not_called()

    @patch('stripe.Price.retrieve')
    def test_free_and_inactive_packages_are_not_checked(self, mock_retrieve):
        """A free package has no price id by design; an inactive one charges nobody."""
        mock_retrieve.return_value = {'active': True}
        Package.objects.create(name='Free', price=Decimal('0'), class_limit=0)
        Package.objects.create(
            name='Retired', price=Decimal('9.90'), stripe_price_id='price_old',
            class_limit=1, is_active=False,
        )
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['checked'], 1)
        self.assertEqual(health['broken'], [])

    @patch('stripe.Price.retrieve')
    def test_institute_plans_are_checked_too(self, mock_retrieve):
        mock_retrieve.return_value = {'active': False}
        InstitutePlan.objects.create(
            name='Basic', slug='basic-health', price=Decimal('89'),
            stripe_price_id='price_plan', class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )
        kinds = {b['kind'] for b in get_stripe_price_health(use_cache=False)['broken']}
        self.assertEqual(kinds, {'Package', 'InstitutePlan'})

    @override_settings(STRIPE_CURRENCY='usd')
    @patch('stripe.Price.retrieve')
    def test_wrong_currency_is_flagged(self, mock_retrieve):
        """All payments are in USD. A stray NZD price charges the wrong amount
        and then currency-locks that customer — both silent."""
        mock_retrieve.return_value = {'active': True, 'currency': 'nzd'}
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'critical')
        problem = health['broken'][0]['problem']
        self.assertIn('NZD', problem)
        self.assertIn('USD', problem)

    @override_settings(STRIPE_CURRENCY='usd')
    @patch('stripe.Price.retrieve')
    def test_matching_currency_is_clean(self, mock_retrieve):
        mock_retrieve.return_value = {'active': True, 'currency': 'usd'}
        self.assertEqual(get_stripe_price_health(use_cache=False)['status'], 'ok')

    @override_settings(STRIPE_CURRENCY='usd')
    @patch('stripe.Price.retrieve')
    def test_archived_price_is_reported_once_not_twice(self, mock_retrieve):
        """An archived NZD price is one problem to fix, not two lines."""
        mock_retrieve.return_value = {'active': False, 'currency': 'nzd'}
        broken = get_stripe_price_health(use_cache=False)['broken']
        self.assertEqual(len(broken), 1)
        self.assertIn('Archived in Stripe', broken[0]['problem'])

    @override_settings(STRIPE_SECRET_KEY='')
    @patch('stripe.Price.retrieve')
    def test_unconfigured_stripe_reports_unknown_not_ok(self, mock_retrieve):
        """Never claim health we did not verify."""
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'unknown')
        self.assertIn('not configured', health['skipped'])
        mock_retrieve.assert_not_called()

    @patch('stripe.Price.retrieve')
    def test_result_is_cached(self, mock_retrieve):
        mock_retrieve.return_value = {'active': True}
        get_stripe_price_health()
        get_stripe_price_health()
        self.assertEqual(mock_retrieve.call_count, 1)


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class CheckStripePricesCommandTest(TestCase):

    def setUp(self):
        cache.clear()
        Package.objects.create(
            name='Student Monthly', price=Decimal('19.90'),
            stripe_price_id='price_live', class_limit=1,
        )

    def tearDown(self):
        cache.clear()

    @patch('stripe.Price.retrieve')
    def test_green_run_says_so(self, mock_retrieve):
        mock_retrieve.return_value = {'active': True}
        out = StringIO()
        call_command('check_stripe_prices', '--fresh', stdout=out, stderr=StringIO())
        self.assertIn('are active', out.getvalue())

    @patch('stripe.Price.retrieve')
    def test_archived_price_exits_non_zero(self, mock_retrieve):
        """A cron that exits 0 on a broken price is how this stayed invisible."""
        mock_retrieve.return_value = {'active': False}
        err = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command('check_stripe_prices', '--fresh',
                         stdout=StringIO(), stderr=err)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn('Student Monthly', err.getvalue())
        self.assertIn('price_live', err.getvalue())


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class OpsDashboardShowsCheckoutFailuresTest(TestCase):
    """The whole point: a super admin sees this without opening a terminal."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.admin = CustomUser.objects.create_superuser(
            'opsadmin', 'ops@test.com', 'pass1234')
        self.student = CustomUser.objects.create_user(
            'kiyali', 'k@test.com', 'x', first_name='Kiyali', last_name='S')
        self.pkg = Package.objects.create(
            name='Student Monthly', price=Decimal('19.90'),
            stripe_price_id='price_live', class_limit=1,
        )
        self.client.force_login(self.admin)

    def tearDown(self):
        cache.clear()

    @patch('stripe.Price.retrieve')
    def test_failed_checkout_and_its_reason_are_on_the_page(self, mock_retrieve):
        mock_retrieve.return_value = {'active': False}
        # Kiyali's real shape: one student retrying because the page told her
        # nothing useful.
        for _ in range(11):
            record_checkout_failure(
                Exception(INACTIVE_PRICE_ERROR), user=self.student,
                package=self.pkg, flow='school_student_complete_profile',
            )
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Failed checkouts')
        self.assertContains(resp, 'kiyali')
        self.assertContains(resp, 'price specified is inactive')
        self.assertContains(resp, 'Archived in Stripe')
        self.assertEqual(resp.context['checkout_failures']['status'], 'critical')
        self.assertEqual(resp.context['stripe_prices']['status'], 'critical')

    @patch('stripe.Price.retrieve')
    def test_quiet_page_when_everything_works(self, mock_retrieve):
        mock_retrieve.return_value = {'active': True}
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.context['checkout_failures']['status'], 'ok')
        self.assertEqual(resp.context['stripe_prices']['status'], 'ok')
        self.assertContains(resp, 'everyone reached the card page')

    @patch('stripe.Price.retrieve')
    def test_non_superuser_cannot_see_it(self, mock_retrieve):
        mock_retrieve.return_value = {'active': True}
        self.client.force_login(self.student)
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertNotEqual(resp.status_code, 200)
