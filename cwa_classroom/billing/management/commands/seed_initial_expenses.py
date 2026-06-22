"""Seed the known recurring operating-expense templates, then materialise them.

One-shot setup for the income-vs-expense dashboard. Edit the EXPENSES table
below and re-run any time — it's idempotent (upserts on category+vendor), so
correcting an amount and re-running just updates the template.

USD amounts are converted to NZD at run time via the live FX helper
(billing.reporting.get_usd_to_nzd_rate); NZD amounts are stored as-is.

    python manage.py seed_initial_expenses [--dry-run]

Claude API cost is NOT seeded here — it auto-syncs from AIGradingUsage.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand

from billing.models import RecurringExpense, ExpenseCategory
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
    {
        'category': ExpenseCategory.CLAUDE_CODE, 'vendor': 'Anthropic',
        'description': 'Claude Code subscription (Max)',
        # Max 5x assumed. ⚠️ If on Max 20x, change to Decimal('200.00').
        # (Pro=20, Max 5x=100, Max 20x=200 USD/mo.)
        'amount': Decimal('100.00'), 'currency': 'USD',
        'frequency': 'monthly', 'start_date': date(2026, 6, 22),
    },
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

        if dry:
            self.stdout.write('Dry run — nothing written, expenses not materialised.')
            return

        self.stdout.write('Materialising recurring expenses...')
        call_command('materialize_recurring_expenses')
        self.stdout.write(self.style.SUCCESS('Done.'))
