"""Seed the known recurring operating-expense templates, then materialise them.

One-shot setup for the income-vs-expense dashboard. Edit the EXPENSES table
below and re-run any time — it's idempotent (upserts on category+vendor), so
correcting an amount and re-running just updates the template.

USD amounts are converted to NZD at run time via the live FX helper
(billing.reporting.get_usd_to_nzd_rate); NZD amounts are stored as-is.

    python manage.py seed_initial_expenses [--dry-run]

Claude API cost is NOT seeded here — it auto-syncs from the taskqueue
AIUsageLog ledger (PDF scan + marking + worksheets).
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand

from billing.models import (
    Expense, RecurringExpense, ExpenseCategory,
    EXPENSE_SOURCE_MANUAL, EXPENSE_SOURCE_RECURRING,
)
from billing.reporting import get_usd_to_nzd_rate


# --- Edit these to match your real bills, then re-run -----------------------
# amount is in the stated `currency`; USD rows are converted to NZD on seed.
# frequency: 'monthly' | 'yearly'. start_date: when the cost first applied.
EXPENSES = [
    {
        'category': ExpenseCategory.DIGITALOCEAN, 'vendor': 'DigitalOcean',
        'description': 'Droplets + Managed DB + Spaces',
        'amount': Decimal('28.68'), 'currency': 'USD',   # May 2026 actual; true-up monthly
        'frequency': 'monthly', 'start_date': date(2026, 5, 11),
    },
    {
        'category': ExpenseCategory.GODADDY, 'vendor': 'GoDaddy',
        'description': '.co.nz domain renewal (wizardslearninghub.co.nz)',
        'amount': Decimal('45.99'), 'currency': 'NZD',   # incl. GST
        'frequency': 'yearly', 'start_date': date(2025, 11, 3),
    },
    {
        'category': ExpenseCategory.RESEND, 'vendor': 'Resend',
        'description': 'Transactional Pro (50k emails)',
        'amount': Decimal('20.00'), 'currency': 'USD',
        'frequency': 'monthly', 'start_date': date(2026, 6, 11),
    },
]

# Claude Code is NOT a flat subscription — there are multiple charges per month
# (plan + usage top-ups) and no billing API, so we book the ACTUAL charges from
# the claude.ai billing page (already in NZD). Add each new month's charge(s)
# here or via the admin UI (Expenses > New). (date, NZD amount) pairs:
CLAUDE_CODE_CHARGES = [
    (date(2026, 3, 1), Decimal('34.78')),
    (date(2026, 3, 6), Decimal('40.00')),
    (date(2026, 3, 6), Decimal('144.85')),
    (date(2026, 4, 6), Decimal('34.78')),
    (date(2026, 4, 13), Decimal('146.70')),
    (date(2026, 5, 13), Decimal('34.78')),
    (date(2026, 5, 17), Decimal('20.00')),
    (date(2026, 6, 11), Decimal('171.90')),
]
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = 'Seed recurring operating-expense templates and materialise them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be seeded without writing.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        rate, source = get_usd_to_nzd_rate()
        self.stdout.write(f'USD->NZD rate: {rate} ({source})')

        for spec in EXPENSES:
            currency = spec['currency'].upper()
            if currency == 'USD':
                nzd = (spec['amount'] * rate).quantize(Decimal('0.01'))
            else:
                nzd = spec['amount'].quantize(Decimal('0.01'))

            label = (
                f"{spec['vendor']} [{spec['frequency']}] "
                f"{spec['amount']} {currency} -> NZ${nzd}"
            )
            if dry:
                self.stdout.write(f'  + would seed {label}')
                continue

            obj, created = RecurringExpense.objects.update_or_create(
                category=spec['category'], vendor=spec['vendor'],
                defaults={
                    'description': spec['description'],
                    'amount': nzd,
                    'frequency': spec['frequency'],
                    'start_date': spec['start_date'],
                    'is_active': True,
                    'note': (
                        f"Seeded from {spec['amount']} {currency}"
                        + (f" @ {rate} ({source})" if currency != 'NZD' else '')
                    ),
                },
            )
            verb = 'created' if created else 'updated'
            self.stdout.write(self.style.SUCCESS(f'  {verb} {label}'))

        # Claude Code: actual NZD charges (variable, no API). Book each as a
        # manual row, and drop any flat Claude Code recurring template a prior
        # seed may have created (it would double-count these actuals).
        cc_total = sum(amount for _, amount in CLAUDE_CODE_CHARGES)
        if dry:
            for d, amount in CLAUDE_CODE_CHARGES:
                self.stdout.write(f'  + would book Claude Code {d} NZ${amount}')
            self.stdout.write(
                f'  (would remove any flat Claude Code template; '
                f'{len(CLAUDE_CODE_CHARGES)} charges, NZ${cc_total} total)')
            self.stdout.write('Dry run — nothing written, expenses not materialised.')
            return

        RecurringExpense.objects.filter(
            category=ExpenseCategory.CLAUDE_CODE).delete()
        Expense.objects.filter(
            category=ExpenseCategory.CLAUDE_CODE,
            source=EXPENSE_SOURCE_RECURRING).delete()
        cc_created = 0
        for d, amount in CLAUDE_CODE_CHARGES:
            _, created = Expense.objects.get_or_create(
                category=ExpenseCategory.CLAUDE_CODE,
                source=EXPENSE_SOURCE_MANUAL,
                incurred_on=d, amount=amount,
                defaults={
                    'vendor': 'Anthropic',
                    'description': 'Claude Code charge',
                    'original_currency': 'NZD',
                },
            )
            cc_created += 1 if created else 0
        self.stdout.write(self.style.SUCCESS(
            f'  Claude Code: {cc_created} new charge(s) booked '
            f'(NZ${cc_total} total across {len(CLAUDE_CODE_CHARGES)}).'))

        self.stdout.write('Materialising recurring expenses...')
        call_command('materialize_recurring_expenses')
        self.stdout.write(self.style.SUCCESS('Done.'))
