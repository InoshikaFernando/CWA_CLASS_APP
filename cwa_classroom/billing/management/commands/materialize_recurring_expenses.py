"""Generate Expense rows from RecurringExpense templates + sync AI grading cost.

Idempotent: re-running never duplicates rows (upsert keyed on template +
month, and on the ai_grading source + month). Intended to run monthly via cron,
but safe to run any time.

    python manage.py materialize_recurring_expenses [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import (
    RecurringExpense, Expense, EXPENSE_SOURCE_RECURRING,
)
from billing.reporting import sync_ai_usage_expenses


def _first_of_month(d):
    return d.replace(day=1)


def _add_month(d):
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


def _add_year(d):
    return d.replace(year=d.year + 1)


def _occurrences(template, until):
    """Yield first-of-month dates this template should book, up to `until`.

    `until` is the (inclusive) current month start. Monthly templates book one
    row per month; yearly templates book one row per year on their start month.
    Bounded by end_date when set.
    """
    cursor = _first_of_month(template.start_date)
    end = _first_of_month(template.end_date) if template.end_date else None
    step = _add_year if template.frequency == RecurringExpense.FREQUENCY_YEARLY else _add_month
    while cursor <= until:
        if end and cursor > end:
            break
        yield cursor
        cursor = step(cursor)


class Command(BaseCommand):
    help = 'Materialise recurring expense templates and sync AI grading cost.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        current_month = _first_of_month(timezone.localdate())

        created = 0
        for template in RecurringExpense.objects.filter(is_active=True):
            for month in _occurrences(template, current_month):
                exists = Expense.objects.filter(
                    recurring=template, incurred_on=month,
                ).exists()
                if exists:
                    continue
                created += 1
                if dry:
                    self.stdout.write(
                        f'  + would create {template.get_category_display()} '
                        f'${template.amount} on {month}'
                    )
                    continue
                Expense.objects.create(
                    recurring=template,
                    category=template.category,
                    vendor=template.vendor,
                    description=template.description,
                    amount=template.amount,
                    incurred_on=month,
                    source=EXPENSE_SOURCE_RECURRING,
                    note=template.note,
                )

        if dry:
            ai_synced = 'skipped (dry-run)'
        else:
            ai_synced = sync_ai_usage_expenses()

        self.stdout.write(self.style.SUCCESS(
            f'Recurring expenses {"to create" if dry else "created"}: {created}. '
            f'AI usage rows synced: {ai_synced}.'
        ))
