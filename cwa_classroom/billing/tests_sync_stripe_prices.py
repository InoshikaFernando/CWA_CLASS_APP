"""
Tests for the sync_stripe_prices management command.

Covers: price matching, null unit_amount handling (CPP-299 fix),
--dry-run mode, --create-missing flag, and module product sync.
"""
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from django.core.management import call_command
from django.test import TestCase, override_settings

from billing.models import InstitutePlan, ModuleProduct, Package


def _make_plan(name='Basic', slug='basic', price='89.00', stripe_price_id='', **kw):
    defaults = dict(
        class_limit=5, student_limit=100, invoice_limit_yearly=500,
        extra_invoice_rate=Decimal('0.30'), trial_days=14, is_active=True, order=1,
    )
    defaults.update(kw)
    return InstitutePlan.objects.create(
        name=name, slug=slug, price=Decimal(price),
        stripe_price_id=stripe_price_id, **defaults,
    )


def _make_package(name='Premium', price='19.00', stripe_price_id='', billing_type='recurring', **kw):
    defaults = dict(class_limit=0, trial_days=14, is_active=True, order=1)
    defaults.update(kw)
    return Package.objects.create(
        name=name, price=Decimal(price),
        stripe_price_id=stripe_price_id, billing_type=billing_type, **defaults,
    )


def _make_module(module='teachers_attendance', name='Teachers Attendance', price='10.00', **kw):
    return ModuleProduct.objects.create(
        module=module, name=name, price=Decimal(price),
        is_active=True, **kw,
    )


def _stripe_price(price_id, amount_cents, product_name, recurring_interval=None,
                   metadata=None, unit_amount=None):
    """Build a mock Stripe Price object."""
    product = SimpleNamespace(
        name=product_name,
        id=f'prod_{product_name.lower().replace(" ", "_")}',
        metadata=metadata or {},
    )
    recurring = SimpleNamespace(interval=recurring_interval) if recurring_interval else None
    return SimpleNamespace(
        id=price_id,
        unit_amount=unit_amount if unit_amount is not None else amount_cents,
        product=product,
        recurring=recurring,
    )


def _stripe_list_response(items, has_more=False):
    """Build a mock Stripe list response."""
    resp = MagicMock()
    resp.data = items
    resp.has_more = has_more
    return resp


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class SyncStripePricesCommandTests(TestCase):

    def _call(self, *args, **kwargs):
        out = StringIO()
        err = StringIO()
        call_command('sync_stripe_prices', *args, stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    # ------------------------------------------------------------------
    # No Stripe key configured
    # ------------------------------------------------------------------
    @override_settings(STRIPE_SECRET_KEY='')
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_no_stripe_key_aborts(self, mock_stripe):
        _out, err = self._call()
        self.assertIn('STRIPE_SECRET_KEY is not set', err)

    # ------------------------------------------------------------------
    # Null unit_amount (metered/tiered prices) — CPP-299 fix
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_null_unit_amount_skipped(self, mock_stripe):
        """Metered prices with unit_amount=None must be skipped without crashing."""
        plan = _make_plan()

        metered_price = _stripe_price(
            'price_metered', None, 'Metered Price',
            recurring_interval='month', unit_amount=None,
        )
        normal_price = _stripe_price(
            'price_normal', 8900, 'Basic Plan', recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response(
            [metered_price, normal_price],
        )

        out, _err = self._call()

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_normal')
        self.assertNotIn('Error', out)

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_multiple_null_unit_amounts_skipped(self, mock_stripe):
        """Multiple metered prices don't crash the command."""
        _make_plan(price='50.00')

        prices = [
            _stripe_price('price_m1', None, 'Metered 1', recurring_interval='month', unit_amount=None),
            _stripe_price('price_m2', None, 'Metered 2', recurring_interval='month', unit_amount=None),
            _stripe_price('price_ok', 5000, 'Flat Rate', recurring_interval='month'),
        ]

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response(prices)

        out, _err = self._call()
        self.assertNotIn('Error', out)

    # ------------------------------------------------------------------
    # Institute plan sync
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_plan_matched_by_price(self, mock_stripe):
        plan = _make_plan(price='89.00')

        stripe_price = _stripe_price(
            'price_plan_89', 8900, 'Basic Plan', recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        self._call()

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_plan_89')

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_plan_already_synced_skipped(self, mock_stripe):
        plan = _make_plan(price='89.00', stripe_price_id='price_plan_89')

        stripe_price = _stripe_price(
            'price_plan_89', 8900, 'Basic Plan', recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        out, _err = self._call()

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_plan_89')
        self.assertIn('already synced', out)

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_plan_no_match_shows_miss(self, mock_stripe):
        _make_plan(price='89.00')

        stripe_price = _stripe_price(
            'price_99', 9900, 'Different Plan', recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        out, _err = self._call()
        self.assertIn('MISS', out)

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_inactive_plans_excluded(self, mock_stripe):
        plan = _make_plan(price='89.00', is_active=False)

        stripe_price = _stripe_price(
            'price_89', 8900, 'Basic Plan', recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        self._call()

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, '')

    # ------------------------------------------------------------------
    # Package sync
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_package_matched_by_price(self, mock_stripe):
        pkg = _make_package(price='19.00')

        stripe_price = _stripe_price(
            'price_pkg_19', 1900, 'Premium Package', recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        self._call()

        pkg.refresh_from_db()
        self.assertEqual(pkg.stripe_price_id, 'price_pkg_19')

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_free_package_skipped(self, mock_stripe):
        pkg = _make_package(name='Free', price='0.00')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([])

        out, _err = self._call()

        pkg.refresh_from_db()
        self.assertEqual(pkg.stripe_price_id, '')
        self.assertIn('free, skipping', out)

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_one_time_package_matches_one_time_price(self, mock_stripe):
        pkg = _make_package(price='29.00', billing_type='one_time')

        recurring_price = _stripe_price(
            'price_rec', 2900, 'Recurring', recurring_interval='month',
        )
        one_time_price = _stripe_price(
            'price_ot', 2900, 'One Time',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response(
            [recurring_price, one_time_price],
        )

        self._call()

        pkg.refresh_from_db()
        self.assertEqual(pkg.stripe_price_id, 'price_ot')

    # ------------------------------------------------------------------
    # Dry-run mode
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_dry_run_does_not_save(self, mock_stripe):
        plan = _make_plan(price='89.00')
        pkg = _make_package(price='19.00')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([
            _stripe_price('price_89', 8900, 'Plan', recurring_interval='month'),
            _stripe_price('price_19', 1900, 'Pkg', recurring_interval='month'),
        ])

        out, _err = self._call('--dry-run')

        plan.refresh_from_db()
        pkg.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, '')
        self.assertEqual(pkg.stripe_price_id, '')
        self.assertIn('DRY RUN', out)
        self.assertIn('no changes saved', out)

    # ------------------------------------------------------------------
    # --create-missing flag
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_create_missing_creates_stripe_product(self, mock_stripe):
        plan = _make_plan(price='89.00')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([])

        mock_stripe.Product.create.return_value = SimpleNamespace(id='prod_new')
        mock_stripe.Price.create.return_value = SimpleNamespace(id='price_new_89')

        out, _err = self._call('--create-missing')

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_new_89')
        self.assertIn('CREATED', out)

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_create_missing_dry_run(self, mock_stripe):
        plan = _make_plan(price='89.00')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([])

        out, _err = self._call('--dry-run', '--create-missing')

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, '')
        self.assertIn('DRY RUN', out)
        self.assertIn('would create', out)

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_create_missing_stripe_error_handled(self, mock_stripe):
        import stripe as stripe_mod
        plan = _make_plan(price='89.00')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([])
        mock_stripe.Product.create.side_effect = stripe_mod.error.StripeError('API error')
        mock_stripe.error = stripe_mod.error

        _out, _err = self._call('--create-missing')

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, '')

    # ------------------------------------------------------------------
    # Module product sync
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_module_matched_by_metadata_slug(self, mock_stripe):
        mod = _make_module()

        stripe_price = _stripe_price(
            'price_ta', 1000, 'Teacher Attendance Module',
            recurring_interval='month',
            metadata={'module_slug': 'teachers_attendance'},
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        self._call()

        mod.refresh_from_db()
        self.assertEqual(mod.stripe_price_id, 'price_ta')

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_module_matched_by_product_name_fallback(self, mock_stripe):
        mod = _make_module(module='students_attendance', name='Students Attendance')

        stripe_price = _stripe_price(
            'price_sa', 1000, 'Students Attendance Tracker',
            recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        self._call()

        mod.refresh_from_db()
        self.assertEqual(mod.stripe_price_id, 'price_sa')

    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_module_progress_reports_matched_by_name(self, mock_stripe):
        mod = _make_module(
            module='student_progress_reports', name='Student Progress Reports',
        )

        stripe_price = _stripe_price(
            'price_pr', 1500, 'Student Progress Report Addon',
            recurring_interval='month',
        )

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([stripe_price])

        self._call()

        mod.refresh_from_db()
        self.assertEqual(mod.stripe_price_id, 'price_pr')

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_paginated_price_fetch(self, mock_stripe):
        plan = _make_plan(price='89.00')

        page1_price = _stripe_price('price_other', 5000, 'Other', recurring_interval='month')
        page2_price = _stripe_price('price_89', 8900, 'Basic', recurring_interval='month')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.side_effect = [
            _stripe_list_response([page1_price], has_more=True),
            _stripe_list_response([page2_price], has_more=False),
        ]

        self._call()

        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_89')

    # ------------------------------------------------------------------
    # Summary output
    # ------------------------------------------------------------------
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_summary_counts(self, mock_stripe):
        _make_plan(price='89.00')
        _make_package(price='19.00')

        mock_stripe.Product.list.return_value = _stripe_list_response([])
        mock_stripe.Price.list.return_value = _stripe_list_response([
            _stripe_price('price_89', 8900, 'Plan', recurring_interval='month'),
            _stripe_price('price_19', 1900, 'Pkg', recurring_interval='month'),
        ])

        out, _err = self._call()

        self.assertIn('updated 1', out)
        self.assertIn('Summary', out)
