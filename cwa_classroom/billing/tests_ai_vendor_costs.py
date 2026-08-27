"""Billed AI vendor cost and token-share apportionment (CPP-383).

No test makes a live vendor call. The fixtures in RealResponseShapeTests are
copied from actual API responses (2026-08-17); the rest cover variants the
parsers tolerate. Unparseable input must raise rather than quietly become
zero — a period we could not price has to read as unknown, never as free.
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
    """Variants the parsers accept, and the ones they must refuse."""

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
        # Distinct sources, so the authoritative one stays identifiable.
        from billing.models import EXPENSE_SOURCE_AI_VENDOR, Expense

        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                openai=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('2'))])):
            sync_ai_vendor_expenses()

        self.assertEqual(
            Expense.objects.get(vendor='OpenAI').source,
            EXPENSE_SOURCE_AI_VENDOR)

    def test_billed_figure_replaces_that_month_s_token_estimate(self):
        """The vendor's bill and the ledger's estimate price the same tokens.
        Leaving both in a month doubles that vendor's spend."""
        from billing.models import (
            EXPENSE_SOURCE_AI_GRADING, EXPENSE_SOURCE_AI_VENDOR, Expense,
            ExpenseCategory,
        )

        Expense.objects.create(
            category=ExpenseCategory.OPENAI_API, vendor='OpenAI',
            amount=Decimal('12.00'), incurred_on=date(2026, 8, 1),
            source=EXPENSE_SOURCE_AI_GRADING,
        )
        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                openai=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('2'))])):
            sync_ai_vendor_expenses()

        rows = Expense.objects.filter(category=ExpenseCategory.OPENAI_API)
        self.assertEqual([r.source for r in rows], [EXPENSE_SOURCE_AI_VENDOR])

    def test_a_month_the_vendor_did_not_cover_keeps_its_estimate(self):
        # Superseding is per month: an earlier month with no billed figure must
        # keep the estimate rather than being blanked.
        from billing.models import (
            EXPENSE_SOURCE_AI_GRADING, Expense, ExpenseCategory,
        )

        Expense.objects.create(
            category=ExpenseCategory.OPENAI_API, vendor='OpenAI',
            amount=Decimal('12.00'), incurred_on=date(2026, 7, 1),
            source=EXPENSE_SOURCE_AI_GRADING,
        )
        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                openai=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('2'))])):
            sync_ai_vendor_expenses()

        self.assertTrue(Expense.objects.filter(
            source=EXPENSE_SOURCE_AI_GRADING,
            incurred_on=date(2026, 7, 1)).exists())

    def test_one_vendor_s_estimate_is_not_touched_by_the_other_s_bill(self):
        from billing.models import (
            EXPENSE_SOURCE_AI_GRADING, Expense, ExpenseCategory,
        )

        Expense.objects.create(
            category=ExpenseCategory.CLAUDE_API, vendor='Anthropic',
            amount=Decimal('90.00'), incurred_on=date(2026, 8, 1),
            source=EXPENSE_SOURCE_AI_GRADING,
        )
        with mock.patch.dict(ai_vendor_costs.FETCHERS, self._fetchers(
                openai=lambda s, e: [DailyCost(date(2026, 8, 3), Decimal('2'))])):
            sync_ai_vendor_expenses()

        self.assertTrue(Expense.objects.filter(
            category=ExpenseCategory.CLAUDE_API,
            source=EXPENSE_SOURCE_AI_GRADING).exists())


# ---------------------------------------------------------------------------
# Fixtures copied from real API responses (2026-08-17), trimmed for length.
# These are the shapes in production, not shapes I assumed.
# ---------------------------------------------------------------------------
REAL_OPENAI_PAGE = {
    'object': 'page',
    'data': [
        {'object': 'bucket', 'start_time': 1786320000,
         'start_time_iso': '2026-08-10T00:00:00+00:00',
         'end_time': 1786406400, 'results': []},
        {'object': 'bucket', 'start_time': 1786406400,
         'start_time_iso': '2026-08-11T00:00:00+00:00',
         'end_time': 1786492800, 'results': []},
    ],
    'has_more': True,
    'next_page': 'page_AAAAAGqD469KskwwAAAAAGqCTwA=',
}

REAL_ANTHROPIC_PAGE = {
    'data': [
        {'starting_at': '2026-08-10T00:00:00Z',
         'ending_at': '2026-08-11T00:00:00Z',
         'results': [{'currency': 'USD', 'amount': '326.237',
                      'workspace_id': None, 'description': None,
                      'cost_type': None, 'model': None}]},
        {'starting_at': '2026-08-11T00:00:00Z',
         'ending_at': '2026-08-12T00:00:00Z',
         'results': [{'currency': 'USD', 'amount': '590.1895',
                      'workspace_id': None, 'model': None}]},
    ],
    'has_more': False,
    'next_page': None,
}


class RealResponseShapeTests(TestCase):
    """Locked to the payloads the live APIs actually returned."""

    def test_anthropic_amount_is_a_string_beside_its_currency(self):
        # {"currency": "USD", "amount": "326.237"} — not a nested money object.
        costs = _extract_daily_costs(REAL_ANTHROPIC_PAGE)
        self.assertEqual(costs[0].on, date(2026, 8, 10))
        self.assertEqual(costs[0].amount_usd, Decimal('326.237'))
        self.assertEqual(costs[1].amount_usd, Decimal('590.1895'))

    def test_openai_epoch_buckets_with_no_spend_are_zero_not_an_error(self):
        # Empty `results` is a real, legitimate answer: nothing billed that day.
        costs = _extract_daily_costs(REAL_OPENAI_PAGE)
        self.assertEqual(costs[0].on, date(2026, 8, 10))
        self.assertEqual(costs[0].amount_usd, Decimal('0'))

    def test_non_usd_sibling_currency_is_refused(self):
        # The currency sits beside the amount in Anthropic's shape; converting
        # a non-USD figure as if it were dollars would be silently wrong.
        payload = {'data': [{'starting_at': '2026-08-10T00:00:00Z',
                             'results': [{'currency': 'EUR',
                                          'amount': '100.00'}]}]}
        with self.assertRaises(VendorCostUnavailable):
            _extract_daily_costs(payload)


class PaginationTests(TestCase):
    """Both endpoints page; a partial read must never pass as a total."""

    @override_settings(OPENAI_ADMIN_API_KEY='sk-admin-test')
    def test_all_pages_are_followed(self):
        page_two = {
            'object': 'page',
            'data': [{'object': 'bucket', 'start_time': 1786492800,
                      'results': [{'amount': {'value': 5, 'currency': 'usd'}}]}],
            'has_more': False, 'next_page': None,
        }
        responses = [REAL_OPENAI_PAGE, page_two]
        seen_params = []

        def _fake_get(url, headers=None, params=None, timeout=None):
            seen_params.append(dict(params or {}))
            payload = responses[len(seen_params) - 1]
            return mock.Mock(json=lambda: payload, raise_for_status=lambda: None)

        with mock.patch('billing.ai_vendor_costs.requests.get', _fake_get):
            costs = fetch_openai_costs(date(2026, 8, 10), date(2026, 8, 17))

        # Two buckets from page one, one from page two — not just page one.
        self.assertEqual(len(costs), 3)
        self.assertEqual(costs[2].amount_usd, Decimal('5'))
        # The cursor from page one was sent with the second request.
        self.assertEqual(seen_params[1]['page'],
                         'page_AAAAAGqD469KskwwAAAAAGqCTwA=')

    @override_settings(OPENAI_ADMIN_API_KEY='sk-admin-test')
    def test_endless_paging_raises_rather_than_returning_a_partial_total(self):
        forever = {'data': [{'start_time': 1786320000, 'results': []}],
                   'has_more': True, 'next_page': 'cursor'}

        with mock.patch('billing.ai_vendor_costs.requests.get',
                        return_value=mock.Mock(json=lambda: forever,
                                               raise_for_status=lambda: None)):
            with self.assertRaises(VendorCostUnavailable):
                fetch_openai_costs(date(2026, 8, 10), date(2026, 8, 17))


class AmountUnitTests(TestCase):
    """Providers do not agree on units; getting it wrong is a 100x error.

    Anthropic reports CENTS — verified 2026-08-17 against the Console, which
    showed $41.49 for the month while the API returned 2470.232 for a single
    week of it.
    """

    @override_settings(ANTHROPIC_ADMIN_API_KEY='sk-ant-admin-test')
    def test_anthropic_cents_become_dollars(self):
        from billing.ai_vendor_costs import fetch_anthropic_costs

        with mock.patch('billing.ai_vendor_costs.requests.get',
                        return_value=mock.Mock(
                            json=lambda: REAL_ANTHROPIC_PAGE,
                            raise_for_status=lambda: None)):
            costs = fetch_anthropic_costs(date(2026, 8, 10), date(2026, 8, 17))

        # 326.237 cents -> $3.26237, not $326.24
        self.assertEqual(costs[0].amount_usd, Decimal('3.26237'))
        self.assertEqual(costs[1].amount_usd, Decimal('5.901895'))

    @override_settings(ANTHROPIC_ADMIN_API_KEY='sk-ant-admin-test')
    def test_a_real_week_totals_a_plausible_figure(self):
        # The seven real days summed to 2470.232 in the API's units. Against a
        # month-to-date spend of $41.49, only the cents reading is possible.
        from billing.ai_vendor_costs import AMOUNT_TO_USD

        week_in_api_units = Decimal('2470.232')
        self.assertEqual(week_in_api_units * AMOUNT_TO_USD['anthropic'],
                         Decimal('24.70232'))

    def test_openai_amounts_are_treated_as_dollars(self):
        from billing.ai_vendor_costs import AMOUNT_TO_USD

        # Documented as {value, currency}; unverified against non-zero data,
        # which is recorded in AMOUNT_TO_USD rather than left implicit.
        self.assertEqual(AMOUNT_TO_USD['openai'], Decimal('1'))


class ReconciliationTests(TestCase):
    """The figures were reconciled against the vendor's own billing page.

    On 2026-08-17 the Console showed $41.49 spent for August, and a single
    request with limit=31 returned 16 daily buckets totalling 4148.8985 in the
    API's units. That is the evidence for the cents divisor — an exact match,
    not an estimate — and it is pinned here so a future change to the divisor
    has to explain itself.
    """

    def test_the_real_month_matches_the_console_to_the_cent(self):
        from billing.ai_vendor_costs import AMOUNT_TO_USD

        api_units_for_august = Decimal('4148.8985')
        console_says = Decimal('41.49')
        converted = api_units_for_august * AMOUNT_TO_USD['anthropic']
        self.assertEqual(converted.quantize(Decimal('0.01')), console_says)

    def test_anthropic_requests_a_full_month_per_page(self):
        # The default page is 7 days; a month would otherwise take 5 requests.
        from billing.ai_vendor_costs import fetch_anthropic_costs

        captured = {}

        def _fake_get(url, headers=None, params=None, timeout=None):
            captured.update(params or {})
            return mock.Mock(json=lambda: {'data': [], 'has_more': False},
                             raise_for_status=lambda: None)

        with override_settings(ANTHROPIC_ADMIN_API_KEY='sk-ant-admin-test'), \
             mock.patch('billing.ai_vendor_costs.requests.get', _fake_get):
            fetch_anthropic_costs(date(2026, 8, 1), date(2026, 8, 17))

        self.assertEqual(captured['limit'], 31)
