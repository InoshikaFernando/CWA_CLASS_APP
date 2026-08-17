"""Billed AI vendor cost and token-share apportionment (CPP-383).

No test makes a live vendor call. The response parsers are exercised against
fixtures because the real shapes could not be verified when this was written —
which is precisely why they are isolated and why unparseable input must raise
rather than quietly become zero.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from billing import ai_vendor_costs
from billing.ai_vendor_costs import (
    DailyCost, VendorCostUnavailable, _extract_daily_costs, fetch_openai_costs,
)
from billing.reporting import apportion_billed_cost, sync_ai_vendor_expenses


class ApportionmentTests(TestCase):
    """The total is the vendor's; the split is derived from tokens."""

    def test_split_is_proportional_to_tokens(self):
        shares = apportion_billed_cost(Decimal('10'),
                                       [(1, 600), (2, 300), (3, 100)])
        self.assertEqual(shares[1], Decimal('6.00000'))
        self.assertEqual(shares[2], Decimal('3.00000'))
        self.assertEqual(shares[3], Decimal('1.00000'))

    def test_parts_always_sum_to_the_billed_total(self):
        # Three equal shares of $10 do not divide evenly; the parts must still
        # add up to the invoice, not 9.99999.
        shares = apportion_billed_cost(Decimal('10'), [(1, 1), (2, 1), (3, 1)])
        self.assertEqual(sum(shares.values()), Decimal('10.00000'))

    def test_rounding_remainder_goes_to_the_largest_consumer(self):
        shares = apportion_billed_cost(Decimal('10'), [(1, 1), (2, 1), (3, 98)])
        self.assertEqual(sum(shares.values()), Decimal('10.00000'))
        self.assertGreater(shares[3], shares[1])

    def test_no_usage_apportions_nothing(self):
        self.assertEqual(apportion_billed_cost(Decimal('10'), []), {})
        self.assertEqual(
            apportion_billed_cost(Decimal('10'), [(1, 0), (2, 0)]), {})

    def test_no_bill_apportions_nothing(self):
        self.assertEqual(
            apportion_billed_cost(Decimal('0'), [(1, 100)]), {})


class ResponseParsingTests(TestCase):
    """Shapes are unverified against the live APIs — so they must fail loudly."""

    def test_epoch_bucket_start(self):
        costs = _extract_daily_costs({'data': [
            {'start_time': 1730419200, 'results': [{'amount': 1.25}]},
        ]})
        self.assertEqual(costs[0].amount_usd, Decimal('1.25'))

    def test_iso_bucket_start(self):
        costs = _extract_daily_costs({'data': [
            {'starting_at': '2026-08-01T00:00:00Z', 'results': [{'amount': '2'}]},
        ]})
        self.assertEqual(costs[0].on, date(2026, 8, 1))
        self.assertEqual(costs[0].amount_usd, Decimal('2'))

    def test_amount_as_value_currency_object(self):
        costs = _extract_daily_costs({'data': [
            {'start_time': 1730419200,
             'results': [{'amount': {'value': 3.5, 'currency': 'usd'}}]},
        ]})
        self.assertEqual(costs[0].amount_usd, Decimal('3.5'))

    def test_entries_in_a_bucket_are_summed(self):
        costs = _extract_daily_costs({'data': [
            {'start_time': 1730419200,
             'results': [{'amount': 1}, {'amount': 2}, {'amount': 0.5}]},
        ]})
        self.assertEqual(costs[0].amount_usd, Decimal('3.5'))

    def test_non_usd_is_refused(self):
        with self.assertRaises(VendorCostUnavailable):
            _extract_daily_costs({'data': [
                {'start_time': 1730419200,
                 'results': [{'amount': {'value': 1, 'currency': 'eur'}}]},
            ]})

    def test_unrecognised_payload_raises_rather_than_returning_zero(self):
        # The whole point: a shape we cannot read must not look like "$0 spent".
        with self.assertRaises(VendorCostUnavailable):
            _extract_daily_costs({'unexpected': []})

    def test_bucket_without_a_start_raises(self):
        with self.assertRaises(VendorCostUnavailable):
            _extract_daily_costs({'data': [{'results': [{'amount': 1}]}]})


class SelfGatingTests(TestCase):

    @override_settings(OPENAI_ADMIN_API_KEY='')
    def test_absent_admin_key_returns_none_not_zero(self):
        self.assertIsNone(fetch_openai_costs(date(2026, 8, 1), date(2026, 8, 17)))

    @override_settings(OPENAI_ADMIN_API_KEY='sk-admin-test')
    def test_transport_failure_is_reported_not_swallowed(self):
        import requests
        with mock.patch('billing.ai_vendor_costs.requests.get',
                        side_effect=requests.RequestException('boom')):
            with self.assertRaises(VendorCostUnavailable):
                fetch_openai_costs(date(2026, 8, 1), date(2026, 8, 17))


class SyncBilledExpensesTests(TestCase):

    def _fetchers(self, **overrides):
        base = {'anthropic': lambda s, e: None, 'openai': lambda s, e: None}
        base.update(overrides)
        return base

    def test_each_vendor_gets_its_own_billed_row(self):
        from billing.models import Expense, ExpenseCategory

        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                anthropic=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('6'))],
                openai=lambda s, e: [DailyCost(date(2026, 8, 4), Decimal('2'))])):
            result = sync_ai_vendor_expenses()

        self.assertEqual(result['written'], 2)
        self.assertTrue(Expense.objects.filter(
            category=ExpenseCategory.CLAUDE_API, vendor='Anthropic').exists())
        self.assertTrue(Expense.objects.filter(
            category=ExpenseCategory.OPENAI_API, vendor='OpenAI').exists())

    def test_days_are_rolled_up_per_month(self):
        from billing.models import Expense

        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                openai=lambda s, e: [
                    DailyCost(date(2026, 8, 3), Decimal('1.50')),
                    DailyCost(date(2026, 8, 4), Decimal('2.50')),
                ])):
            sync_ai_vendor_expenses()

        row = Expense.objects.get(vendor='OpenAI')
        self.assertEqual(row.original_amount, Decimal('4.000000'))

    def test_missing_key_is_skipped_with_a_reason_and_no_row(self):
        from billing.models import Expense

        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers()):
            result = sync_ai_vendor_expenses()

        self.assertEqual(result['written'], 0)
        self.assertEqual(Expense.objects.count(), 0)
        reasons = dict(result['skipped'])
        self.assertIn('admin API key', reasons['openai'])

    def test_vendor_error_leaves_no_row_rather_than_a_zero(self):
        # A period we could not price must look unknown, never free.
        from billing.models import Expense

        def _explode(start, end):
            raise VendorCostUnavailable('API 500')

        with mock.patch.dict(ai_vendor_costs.FETCHERS,
                             self._fetchers(openai=_explode)):
            result = sync_ai_vendor_expenses()

        self.assertEqual(Expense.objects.filter(vendor='OpenAI').count(), 0)
        self.assertIn('openai', dict(result['skipped']))

    def test_sync_is_idempotent(self):
        from billing.models import Expense

        fetchers = self._fetchers(
            openai=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('2'))])
        with mock.patch.dict(ai_vendor_costs.FETCHERS, fetchers):
            sync_ai_vendor_expenses()
            sync_ai_vendor_expenses()

        self.assertEqual(Expense.objects.filter(vendor='OpenAI').count(), 1)

    def test_billed_rows_are_distinct_from_the_estimate_rows(self):
        # Both can coexist during the switchover; they must not collide.
        from billing.models import EXPENSE_SOURCE_AI_VENDOR, Expense

        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                openai=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('2'))])):
            sync_ai_vendor_expenses()

        self.assertEqual(
            Expense.objects.get(vendor='OpenAI').source,
            EXPENSE_SOURCE_AI_VENDOR)
