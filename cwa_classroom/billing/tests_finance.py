"""Tests for the income-vs-expense dashboard, expense models and the
materialize_recurring_expenses command.

Stripe is never called: get_paid_revenue is patched so income is deterministic
(or unavailable) without hitting the API.
"""
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from billing.models import (
    Expense, RecurringExpense, ExpenseCategory,
    EXPENSE_SOURCE_MANUAL, EXPENSE_SOURCE_RECURRING, EXPENSE_SOURCE_AI_GRADING,
    EXPENSE_SOURCE_DIGITALOCEAN,
)
from billing.reporting import (
    get_income_expense_summary, sync_ai_usage_expenses,
    sync_digitalocean_expenses, StripeUnavailable,
    get_usd_to_nzd_rate, FX_CACHE_KEY,
)
from taskqueue.models import AIUsageLog

User = get_user_model()


def _revenue(student='0', institute='0'):
    return {
        'student': Decimal(student), 'institute': Decimal(institute),
        'student_count': 0, 'institute_count': 0, 'currency': 'NZD',
    }


class ExpenseModelTests(TestCase):
    def test_is_auto_property(self):
        manual = Expense(source=EXPENSE_SOURCE_MANUAL)
        recurring = Expense(source=EXPENSE_SOURCE_RECURRING)
        self.assertFalse(manual.is_auto)
        self.assertTrue(recurring.is_auto)


class IncomeExpenseSummaryTests(TestCase):
    def setUp(self):
        # Two expenses in the current month, one prior month.
        self.this_month = date.today().replace(day=1)
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('40.00'),
            incurred_on=self.this_month, source=EXPENSE_SOURCE_MANUAL,
        )
        Expense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('25.00'),
            incurred_on=self.this_month, source=EXPENSE_SOURCE_MANUAL,
        )

    @patch('billing.reporting.get_paid_revenue')
    def test_buckets_expenses_and_nets_against_income(self, mock_rev):
        mock_rev.return_value = _revenue(student='100', institute='50')
        summary = get_income_expense_summary(months=3)

        self.assertTrue(summary['income_available'])
        # 3 months * 150 income each = 450
        self.assertEqual(summary['totals']['income'], Decimal('450'))
        self.assertEqual(summary['totals']['expense'], Decimal('65.00'))
        self.assertEqual(summary['totals']['net'], Decimal('385.00'))

        # Category breakdown sorted desc by amount.
        cats = {c['category']: c['amount'] for c in summary['category_totals']}
        self.assertEqual(cats[ExpenseCategory.DIGITALOCEAN], Decimal('40.00'))
        self.assertEqual(cats[ExpenseCategory.GODADDY], Decimal('25.00'))

        # Latest month bucket has both expenses.
        latest = summary['months'][-1]
        self.assertEqual(latest['expense'], Decimal('65.00'))

    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_stripe_unavailable_flags_income(self, mock_rev):
        summary = get_income_expense_summary(months=2)
        self.assertFalse(summary['income_available'])
        self.assertEqual(summary['totals']['income'], Decimal('0.00'))
        self.assertEqual(summary['totals']['expense'], Decimal('65.00'))

    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_carry_forward_captures_pre_window_net(self, mock_rev):
        # An expense well before any window — must land in carry_forward, not
        # the period, so overall_net reflects it regardless of period length.
        Expense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('45.99'),
            incurred_on=date(2020, 1, 1), source=EXPENSE_SOURCE_MANUAL,
        )
        summary = get_income_expense_summary(months=3)
        # Stripe unavailable -> income_before 0, so carry_forward = -(pre-window).
        self.assertEqual(summary['carry_forward'], Decimal('-45.99'))
        # overall = carry_forward + this-period net (the setUp's -65 expense).
        self.assertEqual(
            summary['overall_net'],
            summary['carry_forward'] + summary['totals']['net'],
        )
        # The pre-window expense is NOT double-counted in the period total.
        self.assertEqual(summary['totals']['expense'], Decimal('65.00'))


class SyncAIUsageTests(TestCase):
    """Anthropic cost is summed from the full AIUsageLog ledger (scan + marking
    + worksheets), not just grading — so new AI features flow in automatically."""

    def _log(self, source, usd):
        return AIUsageLog.objects.create(
            source=source, pages=1, est_cost_usd=Decimal(usd),
        )

    @patch('billing.reporting.get_usd_to_nzd_rate', return_value=(Decimal('1.65'), 'live'))
    def test_converts_usd_to_nzd_and_is_idempotent(self, mock_rate):
        self._log(AIUsageLog.SOURCE_AI_IMPORT, '10.00')

        first = sync_ai_usage_expenses()
        self.assertEqual(first, 1)
        exp = Expense.objects.get(source=EXPENSE_SOURCE_AI_GRADING)
        self.assertEqual(exp.amount, Decimal('16.50'))  # 10 * 1.65
        self.assertEqual(exp.category, ExpenseCategory.CLAUDE_API)
        self.assertEqual(exp.original_currency, 'USD')

        sync_ai_usage_expenses()
        self.assertEqual(
            Expense.objects.filter(source=EXPENSE_SOURCE_AI_GRADING).count(), 1,
        )

    @patch('billing.reporting.get_usd_to_nzd_rate', return_value=(Decimal('2.0'), 'live'))
    def test_sums_every_source_in_a_month(self, mock_rate):
        self._log(AIUsageLog.SOURCE_AI_IMPORT, '5.00')   # PDF scan
        self._log(AIUsageLog.SOURCE_HOMEWORK, '3.00')    # marking
        self._log(AIUsageLog.SOURCE_WORKSHEET, '2.00')   # worksheets
        sync_ai_usage_expenses()
        exp = Expense.objects.get(source=EXPENSE_SOURCE_AI_GRADING)
        self.assertEqual(exp.amount, Decimal('20.00'))   # (5+3+2) * 2.0


class SyncDigitalOceanTests(TestCase):
    def _resp(self, payload):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.json.return_value = payload
        m.raise_for_status.side_effect = None
        return m

    def test_noop_when_token_unset(self):
        with self.settings(DIGITALOCEAN_API_TOKEN=''):
            self.assertEqual(sync_digitalocean_expenses(), 0)
        self.assertEqual(Expense.objects.count(), 0)

    @patch('billing.reporting.get_usd_to_nzd_rate', return_value=(Decimal('2.0'), 'live'))
    @patch('billing.reporting.requests.get')
    def test_pulls_invoices_and_supersedes_recurring(self, mock_get, mock_rate):
        # A recurring DO estimate already exists for May — should be replaced.
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('49.94'),
            incurred_on=date(2026, 5, 1), source=EXPENSE_SOURCE_RECURRING,
        )
        mock_get.return_value = self._resp({
            'invoices': [{'invoice_period': '2026-05', 'amount': '28.68'}],
        })
        with self.settings(DIGITALOCEAN_API_TOKEN='dop_v1_x'):
            n = sync_digitalocean_expenses()

        self.assertEqual(n, 1)
        do = Expense.objects.get(source=EXPENSE_SOURCE_DIGITALOCEAN)
        self.assertEqual(do.incurred_on, date(2026, 5, 1))
        self.assertEqual(do.amount, Decimal('57.36'))  # 28.68 * 2.0
        self.assertEqual(do.category, ExpenseCategory.DIGITALOCEAN)
        # The recurring estimate for that month is gone (no double-count).
        self.assertFalse(
            Expense.objects.filter(
                source=EXPENSE_SOURCE_RECURRING,
                category=ExpenseCategory.DIGITALOCEAN,
            ).exists(),
        )

    @patch('billing.reporting.requests.get',
           side_effect=__import__('requests').RequestException('boom'))
    def test_api_failure_is_noop(self, mock_get):
        with self.settings(DIGITALOCEAN_API_TOKEN='dop_v1_x'):
            self.assertEqual(sync_digitalocean_expenses(), 0)


class FxRateTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.delete(FX_CACHE_KEY)

    def _resp(self, payload, status=200):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.json.return_value = payload
        m.raise_for_status.side_effect = None
        m.status_code = status
        return m

    @patch('billing.reporting.requests.get')
    def test_live_fetch_parses_and_caches(self, mock_get):
        mock_get.return_value = self._resp({'rates': {'NZD': 1.63}})
        rate, source = get_usd_to_nzd_rate()
        self.assertEqual(rate, Decimal('1.63'))
        self.assertEqual(source, 'live')

        # Second call served from cache — no extra HTTP hit.
        rate2, source2 = get_usd_to_nzd_rate()
        self.assertEqual(source2, 'cache')
        self.assertEqual(mock_get.call_count, 1)

    @patch('billing.reporting.requests.get', side_effect=__import__('requests').RequestException('boom'))
    def test_api_failure_falls_back_to_setting(self, mock_get):
        with self.settings(USD_TO_NZD_RATE=1.70):
            rate, source = get_usd_to_nzd_rate()
        self.assertEqual(rate, Decimal('1.7'))
        self.assertEqual(source, 'fallback')

    def test_disabled_url_uses_fallback_without_http(self):
        with self.settings(FX_RATE_API_URL='', USD_TO_NZD_RATE=1.55):
            rate, source = get_usd_to_nzd_rate()
        self.assertEqual(rate, Decimal('1.55'))
        self.assertEqual(source, 'fallback')

    @patch('billing.reporting.requests.get')
    def test_malformed_response_falls_back(self, mock_get):
        mock_get.return_value = self._resp({'unexpected': True})
        with self.settings(USD_TO_NZD_RATE=1.60):
            rate, source = get_usd_to_nzd_rate()
        self.assertEqual(rate, Decimal('1.6'))
        self.assertEqual(source, 'fallback')


class MaterializeCommandTests(TestCase):
    def _run(self, dry_run=False):
        out = StringIO()
        args = ['materialize_recurring_expenses']
        if dry_run:
            args.append('--dry-run')
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_monthly_template_generates_rows_idempotently(self):
        # Template starting 2 months ago -> 3 monthly rows (incl. current).
        today = date.today().replace(day=1)
        if today.month <= 2:
            start = today.replace(year=today.year - 1, month=today.month + 10)
        else:
            start = today.replace(month=today.month - 2)
        RecurringExpense.objects.create(
            category=ExpenseCategory.CLAUDE_CODE, amount=Decimal('30.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=start,
        )
        self._run()
        self.assertEqual(Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING).count(), 3)

        # Re-run: no duplicates.
        self._run()
        self.assertEqual(Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING).count(), 3)

    def test_dry_run_writes_nothing(self):
        RecurringExpense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('20.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY,
            start_date=date.today().replace(day=1),
        )
        out = self._run(dry_run=True)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertIn('would create', out)

    def test_end_date_bounds_generation(self):
        today = date.today().replace(day=1)
        # Started a year ago, ended 6 months before now -> no current rows.
        start = today.replace(year=today.year - 1)
        end = start.replace(month=1) if start.month != 1 else start
        RecurringExpense.objects.create(
            category=ExpenseCategory.RESEND, amount=Decimal('10.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY,
            start_date=start, end_date=end, is_active=True,
        )
        self._run()
        # All generated rows must fall on/before the end_date month.
        for e in Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING):
            self.assertLessEqual(e.incurred_on, end.replace(day=1))

    def test_inactive_template_skipped(self):
        RecurringExpense.objects.create(
            category=ExpenseCategory.OTHER, amount=Decimal('5.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY,
            start_date=date.today().replace(day=1), is_active=False,
        )
        self._run()
        self.assertEqual(Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING).count(), 0)


class FinanceDashboardViewTests(TestCase):
    def setUp(self):
        self.super = User.objects.create_superuser(
            username='boss', email='boss@example.local', password='Pass123!',
        )
        self.plain = User.objects.create_user(
            username='plain', email='plain@example.local', password='Pass123!',
        )

    def test_requires_superuser(self):
        self.client.login(username='plain', password='Pass123!')
        resp = self.client.get(reverse('billing_admin_finance_dashboard'))
        self.assertEqual(resp.status_code, 302)

    @patch('billing.views_admin.get_usd_to_nzd_rate', return_value=(Decimal('1.63'), 'live'))
    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_renders_for_superuser(self, mock_rev, mock_rate):
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('billing_admin_finance_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Income vs Expenses')

    def test_create_manual_expense(self):
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.post(reverse('billing_admin_expense_create'), {
            'category': ExpenseCategory.DIGITALOCEAN,
            'amount': '42.00', 'incurred_on': '2026-06-01',
            'vendor': 'DigitalOcean',
        })
        self.assertEqual(resp.status_code, 302)
        exp = Expense.objects.get()
        self.assertEqual(exp.amount, Decimal('42.00'))
        self.assertEqual(exp.source, EXPENSE_SOURCE_MANUAL)

    def test_ai_grading_expense_cannot_be_deleted(self):
        self.client.login(username='boss', password='Pass123!')
        auto = Expense.objects.create(
            category=ExpenseCategory.CLAUDE_API, amount=Decimal('16.50'),
            incurred_on=date(2026, 6, 1), source=EXPENSE_SOURCE_AI_GRADING,
        )
        resp = self.client.post(reverse('billing_admin_expense_delete', args=[auto.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Expense.objects.filter(pk=auto.pk).exists())

    def test_recurring_expense_can_be_trued_up(self):
        """Recurring rows (variable costs like DigitalOcean) are editable —
        the cron never overwrites an existing row, so true-ups are safe."""
        self.client.login(username='boss', password='Pass123!')
        tpl = RecurringExpense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('78.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY,
            start_date=date(2026, 6, 1),
        )
        row = Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('78.00'),
            incurred_on=date(2026, 6, 1), source=EXPENSE_SOURCE_RECURRING,
            recurring=tpl,
        )
        resp = self.client.post(reverse('billing_admin_expense_edit', args=[row.pk]), {
            'category': ExpenseCategory.DIGITALOCEAN,
            'amount': '56.74', 'incurred_on': '2026-06-01',
            'vendor': 'DigitalOcean',
        })
        self.assertEqual(resp.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal('56.74'))
