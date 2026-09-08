"""Generate Expense rows from RecurringExpense templates + sync AI grading cost.

Idempotent: re-running never duplicates rows (upsert keyed on template +
month, and on the ai_grading source + month). Intended to run monthly via cron,
but safe to run any time.

    python manage.py materialize_recurring_expenses [--dry-run]
"""
from django.core.management.base import BaseCommand

from billing.reporting import (
    materialize_recurring_expenses, sync_ai_usage_expenses,
)


class Command(BaseCommand):
    help = 'Materialise recurring expense templates and sync AI grading cost.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']

        created = materialize_recurring_expenses(dry_run=dry)
        if dry:
            for template, month in created:
                self.stdout.write(
                    f'  + would create {template.get_category_display()} '
                    f'${template.amount} on {month}'
                )
            ai_synced = 'skipped (dry-run)'
        else:
            ai_synced = sync_ai_usage_expenses()

        self.stdout.write(self.style.SUCCESS(
            f'Recurring expenses {"to create" if dry else "created"}: '
            f'{len(created)}. AI usage rows synced: {ai_synced}.'
        ))
