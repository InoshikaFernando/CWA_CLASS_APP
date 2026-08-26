"""Tests for the income-vs-expense dashboard, expense models and the
materialize_recurring_expenses command.

Stripe is never called: get_paid_revenue is patched so income is deterministic
(or unavailable) without hitting the API.
"""
from datetime import date, timedelta
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
    materialize_recurring_expenses, refresh_current_month_expenses,
    FINANCE_REFRESH_LOCK_KEY,
)
from taskqueue.models import AIUsageLog

User = get_user_model()


def _revenue(student='0', institute='0'):
    return {
        'student': Decimal(student), 'institute': Decimal(institute),
        'student_count': 0, 'institute_count': 0, 'currency': 'NZD',
    }


class ExpenseModelTests(TestCase):
    def test_github_is_an_expense_category(self):
        """GitHub Actions minutes are a real operating cost (the CI matrix),
        so they need a bucket of their own rather than landing in Other."""
        self.assertIn(
            (ExpenseCategory.GITHUB, 'GitHub (Actions)'),
            ExpenseCategory.choices,
        )
        exp = Expense.objects.create(
            category=ExpenseCategory.GITHUB, vendor='GitHub',
            amount=Decimal('18.40'), incurred_on=date(2026, 8, 1),
            source=EXPENSE_SOURCE_MANUAL,
        )
        self.assertEqual(exp.get_category_display(), 'GitHub (Actions)')

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

    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_category_with_no_current_charge_is_flagged_stale(self, mock_rev):
        """Claude Code has no billing API — its charges are typed in by hand,
        so a month nobody entered read as $0 and the period total silently
        showed one month's charge for a three-month window. Say so instead."""
        two_ago = self._sub_months(self.this_month, 2)
        Expense.objects.create(
            category=ExpenseCategory.CLAUDE_CODE, amount=Decimal('171.90'),
            incurred_on=two_ago, source=EXPENSE_SOURCE_MANUAL,
        )
        summary = get_income_expense_summary(months=3)

        cats = {c['category']: c for c in summary['category_totals']}
        self.assertTrue(cats[ExpenseCategory.CLAUDE_CODE]['is_stale'])
        self.assertEqual(cats[ExpenseCategory.CLAUDE_CODE]['last_on'], two_ago)
        # A category charged this month is current, not stale.
        self.assertFalse(cats[ExpenseCategory.DIGITALOCEAN]['is_stale'])
        self.assertEqual(
            [c['category'] for c in summary['stale_categories']],
            [ExpenseCategory.CLAUDE_CODE],
        )

    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_yearly_cost_is_never_stale(self, mock_rev):
        """One charge a year is correct for a yearly template — flagging it
        would cry wolf every month."""
        RecurringExpense.objects.create(
            category=ExpenseCategory.GODADDY, vendor='GoDaddy',
            amount=Decimal('45.99'),
            frequency=RecurringExpense.FREQUENCY_YEARLY,
            start_date=self._sub_months(self.this_month, 2),
        )
        Expense.objects.filter(category=ExpenseCategory.GODADDY).update(
            incurred_on=self._sub_months(self.this_month, 2),
        )
        summary = get_income_expense_summary(months=3)

        cats = {c['category']: c for c in summary['category_totals']}
        self.assertFalse(cats[ExpenseCategory.GODADDY]['is_stale'])
        self.assertEqual(summary['stale_categories'], [])

    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_period_label_names_the_window(self, mock_rev):
        summary = get_income_expense_summary(months=3)
        self.assertEqual(
            summary['period_label'],
            f'{self._sub_months(self.this_month, 2).strftime("%b %Y")} – '
            f'{self.this_month.strftime("%b %Y")}',
        )

    @staticmethod
    def _sub_months(d, n):
        for _ in range(n):
            d = (d - timedelta(days=1)).replace(day=1)
        return d


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

    def test_billed_month_is_not_re_estimated(self):
        """Regression: the DigitalOcean estimate came back after the actual
        invoice superseded it, so the month counted twice (the dashboard read
        roughly double for DigitalOcean)."""
        today = date.today().replace(day=1)
        RecurringExpense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, vendor='DigitalOcean',
            amount=Decimal('50.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=today,
        )
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('57.36'),
            incurred_on=today, source=EXPENSE_SOURCE_DIGITALOCEAN,
        )

        self._run()

        rows = Expense.objects.filter(incurred_on=today)
        self.assertEqual([r.source for r in rows], [EXPENSE_SOURCE_DIGITALOCEAN])
        self.assertEqual(
            sum(r.amount for r in rows), Decimal('57.36'),
        )

    def test_existing_superseded_estimate_is_cleared(self):
        """An estimate already double-booked alongside the actual is removed,
        so figures self-heal without a manual clean-up."""
        today = date.today().replace(day=1)
        tpl = RecurringExpense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, vendor='DigitalOcean',
            amount=Decimal('50.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=today,
        )
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('50.00'),
            incurred_on=today, source=EXPENSE_SOURCE_RECURRING, recurring=tpl,
        )
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('57.36'),
            incurred_on=today, source=EXPENSE_SOURCE_DIGITALOCEAN,
        )

        self._run()

        self.assertFalse(
            Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING).exists(),
        )

    def test_dry_run_never_clears_a_superseded_estimate(self):
        today = date.today().replace(day=1)
        tpl = RecurringExpense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, vendor='DigitalOcean',
            amount=Decimal('50.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=today,
        )
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('50.00'),
            incurred_on=today, source=EXPENSE_SOURCE_RECURRING, recurring=tpl,
        )
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('57.36'),
            incurred_on=today, source=EXPENSE_SOURCE_DIGITALOCEAN,
        )

        self._run(dry_run=True)

        self.assertTrue(
            Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING).exists(),
        )

    def test_unbilled_month_still_gets_its_estimate(self):
        """Superseding is per month — a month DigitalOcean hasn't invoiced yet
        must still show the estimate rather than $0."""
        today = date.today().replace(day=1)
        prev = (today - timedelta(days=1)).replace(day=1)
        RecurringExpense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, vendor='DigitalOcean',
            amount=Decimal('50.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=prev,
        )
        Expense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('57.36'),
            incurred_on=prev, source=EXPENSE_SOURCE_DIGITALOCEAN,
        )

        self._run()

        self.assertEqual(
            [(e.incurred_on, e.amount) for e in Expense.objects.filter(
                source=EXPENSE_SOURCE_RECURRING)],
            [(today, Decimal('50.00'))],
        )


class RefreshCurrentMonthExpensesTests(TestCase):
    """The dashboard self-heals the current month between monthly cron runs, so
    an active recurring template shows immediately instead of reading $0."""

    def setUp(self):
        from django.core.cache import cache
        cache.delete(FINANCE_REFRESH_LOCK_KEY)

    @staticmethod
    def _sub_months(d, n):
        m, y = d.month - n, d.year
        while m <= 0:
            m += 12
            y -= 1
        return d.replace(year=y, month=m)

    def test_refresh_books_current_month_recurring_row(self):
        today = date.today().replace(day=1)
        RecurringExpense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('20.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY,
            start_date=self._sub_months(today, 2),
        )
        # Cron hasn't run — nothing materialised yet.
        self.assertEqual(Expense.objects.count(), 0)

        refresh_current_month_expenses()

        # The current month (and the two prior) now have a recurring row.
        self.assertEqual(
            Expense.objects.filter(source=EXPENSE_SOURCE_RECURRING).count(), 3,
        )
        self.assertTrue(
            Expense.objects.filter(
                source=EXPENSE_SOURCE_RECURRING, incurred_on=today).exists(),
        )

    def test_materialize_is_idempotent_and_preserves_true_ups(self):
        today = date.today().replace(day=1)
        tpl = RecurringExpense.objects.create(
            category=ExpenseCategory.DIGITALOCEAN, amount=Decimal('80.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=today,
        )
        self.assertEqual(len(materialize_recurring_expenses()), 1)
        # Operator trues the row up to the real charge.
        row = Expense.objects.get(recurring=tpl, incurred_on=today)
        row.amount = Decimal('56.74')
        row.save(update_fields=['amount'])
        # Re-running creates nothing and never overwrites the true-up.
        self.assertEqual(len(materialize_recurring_expenses()), 0)
        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal('56.74'))

    def test_existence_check_is_bulk_not_per_month(self):
        """Re-materialising a long-running template must not scale its query
        count with the number of months already booked (was one .exists() per
        month, now a single bulk fetch)."""
        old_start = self._sub_months(date.today().replace(day=1), 18)
        RecurringExpense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('20.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=old_start,
        )
        materialize_recurring_expenses()  # first run books ~19 months
        # Second run creates nothing; it must not fan out into one query per
        # already-booked month — just the template list (1) plus two bulk
        # fetches (vendor-billed months, already-booked months), regardless of
        # how many months are already booked.
        with self.assertNumQueries(3):
            self.assertEqual(len(materialize_recurring_expenses()), 0)

    def test_vendor_sync_failure_does_not_break_refresh(self):
        today = date.today().replace(day=1)
        RecurringExpense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('15.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=today,
        )
        with patch('billing.reporting.sync_ai_usage_expenses',
                   side_effect=RuntimeError('boom')):
            refresh_current_month_expenses()  # must not raise
        # Recurring row still booked despite the vendor-sync failure.
        self.assertTrue(
            Expense.objects.filter(
                source=EXPENSE_SOURCE_RECURRING, incurred_on=today).exists(),
        )


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

    @patch('billing.views_admin.get_usd_to_nzd_rate', return_value=(Decimal('1.63'), 'live'))
    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_current_month_expense_materialised_on_load(self, mock_rev, mock_rate):
        """Regression: an active recurring template must show for the current
        month even when the monthly cron hasn't run yet (was reading $0)."""
        from django.core.cache import cache
        cache.delete(FINANCE_REFRESH_LOCK_KEY)
        this_month = date.today().replace(day=1)
        RecurringExpense.objects.create(
            category=ExpenseCategory.GODADDY, amount=Decimal('20.00'),
            frequency=RecurringExpense.FREQUENCY_MONTHLY, start_date=this_month,
        )
        self.assertEqual(Expense.objects.count(), 0)  # cron hasn't run

        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('billing_admin_finance_dashboard'))

        self.assertEqual(resp.status_code, 200)
        current = resp.context['bars'][-1]
        self.assertEqual(current['expense'], Decimal('20.00'))

    @patch('billing.views_admin.get_usd_to_nzd_rate', return_value=(Decimal('1.63'), 'live'))
    @patch('billing.reporting.get_paid_revenue', side_effect=StripeUnavailable)
    def test_stale_category_is_called_out_on_the_page(self, mock_rev, mock_rate):
        this_month = date.today().replace(day=1)
        two_ago = this_month
        for _ in range(2):
            two_ago = (two_ago - timedelta(days=1)).replace(day=1)
        Expense.objects.create(
            category=ExpenseCategory.CLAUDE_CODE, amount=Decimal('171.90'),
            incurred_on=two_ago, source=EXPENSE_SOURCE_MANUAL,
        )

        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('billing_admin_finance_dashboard') + '?months=3')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [c['category'] for c in resp.context['stale_categories']],
            [ExpenseCategory.CLAUDE_CODE],
        )
        self.assertContains(resp, 'Expenses are behind for')
        # The category panel names the window it totals, so a part-period
        # figure can't read as a full one.
        self.assertContains(resp, resp.context['period_label'])

    def test_github_expense_can_be_recorded_from_the_admin_form(self):
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.post(reverse('billing_admin_expense_create'), {
            'category': ExpenseCategory.GITHUB,
            'amount': '18.40', 'incurred_on': '2026-08-01',
            'vendor': 'GitHub', 'description': 'Actions minutes',
        })
        self.assertEqual(resp.status_code, 302)
        exp = Expense.objects.get()
        self.assertEqual(exp.category, ExpenseCategory.GITHUB)
        self.assertEqual(exp.amount, Decimal('18.40'))

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


class AIExpenseProviderSplitTests(TestCase):
    """AI spend is expensed per vendor, not as one merged figure (CPP-382)."""

    def _usage(self, provider, cost, **kwargs):
        return AIUsageLog.objects.create(
            provider=provider,
            source=AIUsageLog.SOURCE_AI_IMPORT,
            pages=1, input_tokens=100, output_tokens=10,
            est_cost_usd=Decimal(cost), **kwargs)

    def test_each_provider_gets_its_own_expense_line(self):
        from billing.models import Expense, ExpenseCategory
        from billing.reporting import sync_ai_usage_expenses

        self._usage(AIUsageLog.PROVIDER_ANTHROPIC, '10.00')
        self._usage(AIUsageLog.PROVIDER_OPENAI, '4.00')

        sync_ai_usage_expenses()

        claude = Expense.objects.filter(category=ExpenseCategory.CLAUDE_API)
        openai = Expense.objects.filter(category=ExpenseCategory.OPENAI_API)
        self.assertEqual(claude.count(), 1)
        self.assertEqual(openai.count(), 1)
        self.assertEqual(claude.first().vendor, 'Anthropic')
        self.assertEqual(openai.first().vendor, 'OpenAI')

    def test_openai_spend_is_not_folded_into_the_anthropic_line(self):
        # The bug: OpenAI cost invisible, or worse, misattributed to Anthropic.
        from billing.models import Expense, ExpenseCategory
        from billing.reporting import sync_ai_usage_expenses

        self._usage(AIUsageLog.PROVIDER_ANTHROPIC, '10.00')
        self._usage(AIUsageLog.PROVIDER_OPENAI, '4.00')
        sync_ai_usage_expenses()

        claude = Expense.objects.get(category=ExpenseCategory.CLAUDE_API)
        openai = Expense.objects.get(category=ExpenseCategory.OPENAI_API)
        # 10 and 4 in USD, kept apart rather than summed to 14 on one row.
        self.assertEqual(claude.original_amount, Decimal('10.000000'))
        self.assertEqual(openai.original_amount, Decimal('4.000000'))

    def test_sync_is_idempotent_per_provider(self):
        from billing.models import Expense
        from billing.reporting import sync_ai_usage_expenses

        self._usage(AIUsageLog.PROVIDER_ANTHROPIC, '10.00')
        self._usage(AIUsageLog.PROVIDER_OPENAI, '4.00')
        sync_ai_usage_expenses()
        sync_ai_usage_expenses()

        self.assertEqual(Expense.objects.count(), 2)

    def test_rows_without_a_provider_are_treated_as_anthropic(self):
        # Historical rows predate the column; they are all Claude.
        from billing.models import Expense, ExpenseCategory
        from billing.reporting import sync_ai_usage_expenses

        AIUsageLog.objects.create(
            source=AIUsageLog.SOURCE_WORKSHEET, pages=1,
            input_tokens=100, output_tokens=10, est_cost_usd=Decimal('3.00'))
        sync_ai_usage_expenses()

        self.assertTrue(Expense.objects.filter(
            category=ExpenseCategory.CLAUDE_API).exists())
        self.assertFalse(Expense.objects.filter(
            category=ExpenseCategory.OPENAI_API).exists())
