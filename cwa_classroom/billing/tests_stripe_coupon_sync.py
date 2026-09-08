"""A partial discount code must never reach checkout without its Stripe coupon.

The coupon id is what carries the discount into Stripe. With it blank the
checkout is built with no discount at all — the student pays the FULL price
while the subscription records the percent they were promised, and until now
nothing said so: the create-time sync logged a warning and reported "created".

These cover the three ways that state is now prevented or repaired: the admin
is told when a sync fails, re-saving the code retries it, and a command finds
the ones already stuck.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from billing.models import DiscountCode, InstituteDiscountCode


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class EnsureStripeCouponTest(TestCase):
    """The helper itself: what it syncs, what it skips, what it reports."""

    def _code(self, percent, coupon_id=''):
        return DiscountCode.objects.create(
            code=f'C{percent}', discount_percent=percent,
            is_active=True, stripe_coupon_id=coupon_id,
        )

    @patch('stripe.Coupon.create')
    def test_partial_code_gets_a_coupon(self, mock_create):
        mock_create.return_value = MagicMock(id='coupon_abc')
        code = self._code(75)
        synced, error = _ensure(code)
        self.assertTrue(synced)
        self.assertIsNone(error)
        code.refresh_from_db()
        self.assertEqual(code.stripe_coupon_id, 'coupon_abc')

    @patch('stripe.Coupon.create')
    def test_percent_off_and_duration_are_sent_to_stripe(self, mock_create):
        """The amount matters — assert what Stripe is actually told."""
        mock_create.return_value = MagicMock(id='coupon_abc')
        code = DiscountCode.objects.create(
            code='REPEAT25', discount_percent=25, is_active=True,
            duration='repeating', duration_in_months=3,
        )
        _ensure(code)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['percent_off'], 25.0)
        self.assertEqual(kwargs['duration'], 'repeating')
        self.assertEqual(kwargs['duration_in_months'], 3)

    @patch('stripe.Coupon.create')
    def test_fully_free_code_needs_no_coupon(self, mock_create):
        """100% never reaches Stripe, so it is synced by definition."""
        synced, error = _ensure(self._code(100))
        self.assertTrue(synced)
        self.assertIsNone(error)
        mock_create.assert_not_called()

    @patch('stripe.Coupon.create')
    def test_already_synced_code_is_not_recreated(self, mock_create):
        synced, _ = _ensure(self._code(75, coupon_id='coupon_existing'))
        self.assertTrue(synced)
        mock_create.assert_not_called()

    @patch('stripe.Coupon.create', side_effect=Exception('Stripe is down'))
    def test_failure_is_reported_not_raised(self, _mock):
        code = self._code(75)
        synced, error = _ensure(code)
        self.assertFalse(synced)
        self.assertIn('Stripe is down', error)
        code.refresh_from_db()
        self.assertEqual(code.stripe_coupon_id, '')

    @override_settings(STRIPE_SECRET_KEY='')
    @patch('stripe.Coupon.create')
    def test_unconfigured_stripe_reports_rather_than_pretending(self, mock_create):
        synced, error = _ensure(self._code(75))
        self.assertFalse(synced)
        self.assertIn('not configured', error)
        mock_create.assert_not_called()


def _ensure(code):
    from billing.stripe_service import ensure_stripe_coupon
    return ensure_stripe_coupon(code)


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class CouponFormSurfacesSyncFailureTest(TestCase):
    """Creating a code whose coupon fails must not report plain success."""

    def setUp(self):
        self.client = Client()
        admin = CustomUser.objects.create_superuser(
            'syncadmin', 'sync@test.com', 'pass1234',
        )
        self.client.force_login(admin)

    def _create(self, code, percent):
        return self.client.post(
            reverse('billing_admin_coupon_create'),
            {'target_type': 'student_discount', 'code': code,
             'discount_percent': str(percent), 'duration': 'forever'},
            follow=True,
        )

    @patch('stripe.Coupon.create', side_effect=Exception('Stripe is down'))
    def test_admin_is_warned_when_the_coupon_fails(self, _mock):
        resp = self._create('BROKEN75', 75)
        self.assertContains(resp, 'could NOT be created')
        self.assertContains(resp, 'charged the full price')
        # The code still exists — it is just unusable until synced.
        self.assertEqual(
            DiscountCode.objects.get(code='BROKEN75').stripe_coupon_id, '')

    @patch('stripe.Coupon.create')
    def test_no_warning_when_the_coupon_syncs(self, mock_create):
        mock_create.return_value = MagicMock(id='coupon_ok')
        resp = self._create('GOOD75', 75)
        self.assertNotContains(resp, 'could NOT be created')
        self.assertEqual(
            DiscountCode.objects.get(code='GOOD75').stripe_coupon_id, 'coupon_ok')

    @patch('stripe.Coupon.create')
    def test_fully_free_code_creates_cleanly_without_stripe(self, mock_create):
        resp = self._create('ALLFREE', 100)
        self.assertNotContains(resp, 'could NOT be created')
        mock_create.assert_not_called()


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class SyncStripeCouponsCommandTest(TestCase):
    """The repair route for codes already stuck without a coupon."""

    def setUp(self):
        self.stuck = DiscountCode.objects.create(
            code='STUCK75', discount_percent=75, is_active=True,
            stripe_coupon_id='',
        )
        self.free = DiscountCode.objects.create(
            code='FREE100', discount_percent=100, is_active=True,
        )
        self.ok = DiscountCode.objects.create(
            code='FINE50', discount_percent=50, is_active=True,
            stripe_coupon_id='coupon_fine',
        )
        self.inst = InstituteDiscountCode.objects.create(
            code='INST20', discount_percent=20, is_active=True,
            stripe_coupon_id='',
        )

    def _run(self, **kw):
        out, err = StringIO(), StringIO()
        call_command('sync_stripe_coupons', stdout=out, stderr=err, **kw)
        return out.getvalue(), err.getvalue()

    @patch('stripe.Coupon.create')
    def test_dry_run_lists_but_writes_nothing(self, mock_create):
        out, _ = self._run(dry_run=True)
        self.assertIn('STUCK75', out)
        self.assertIn('INST20', out)
        self.assertIn('DRY RUN', out)
        # Neither the 100% code nor the already-synced one is listed.
        self.assertNotIn('FREE100', out)
        self.assertNotIn('FINE50', out)
        mock_create.assert_not_called()
        self.stuck.refresh_from_db()
        self.assertEqual(self.stuck.stripe_coupon_id, '')

    @patch('stripe.Coupon.create')
    def test_apply_syncs_only_the_unsynced_partial_codes(self, mock_create):
        mock_create.return_value = MagicMock(id='coupon_new')
        out, _ = self._run()
        self.assertEqual(mock_create.call_count, 2)   # STUCK75 + INST20
        self.stuck.refresh_from_db()
        self.assertEqual(self.stuck.stripe_coupon_id, 'coupon_new')
        self.ok.refresh_from_db()
        self.assertEqual(self.ok.stripe_coupon_id, 'coupon_fine')  # untouched
        self.assertIn('Synced 2 of 2', out)

    @patch('stripe.Coupon.create', side_effect=Exception('Stripe is down'))
    def test_failures_are_reported_on_stderr(self, _mock):
        _, err = self._run()
        self.assertIn('STUCK75', err)
        self.assertIn('full price', err)

    @patch('stripe.Coupon.create')
    def test_clean_database_reports_nothing_to_do(self, mock_create):
        DiscountCode.objects.filter(code='STUCK75').update(
            stripe_coupon_id='coupon_x')
        InstituteDiscountCode.objects.filter(code='INST20').update(
            stripe_coupon_id='coupon_y')
        out, _ = self._run()
        self.assertIn('already has a Stripe coupon', out)
        mock_create.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY='')
    @patch('stripe.Coupon.create')
    def test_refuses_to_run_without_a_stripe_key(self, mock_create):
        _, err = self._run()
        self.assertIn('STRIPE_SECRET_KEY is not set', err)
        mock_create.assert_not_called()

    @patch('stripe.Coupon.create')
    def test_command_is_idempotent(self, mock_create):
        mock_create.return_value = MagicMock(id='coupon_new')
        self._run()
        calls_after_first = mock_create.call_count
        out, _ = self._run()
        self.assertEqual(mock_create.call_count, calls_after_first)
        self.assertIn('already has a Stripe coupon', out)
