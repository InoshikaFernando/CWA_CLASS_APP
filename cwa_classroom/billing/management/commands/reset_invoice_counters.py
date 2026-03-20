"""
Management command to reset yearly invoice usage counters.

Schedule via cron to run on January 1 (or subscription anniversary):
    0 0 1 1 * /path/to/manage.py reset_invoice_counters
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Reset invoices_used_this_year to 0 for all school subscriptions.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be reset without making changes.',
        )

    def handle(self, *args, **options):
        from billing.models import SchoolSubscription

        dry_run = options['dry_run']
        today = timezone.localdate()

        subs = SchoolSubscription.objects.filter(
            invoices_used_this_year__gt=0,
        ).select_related('school', 'plan')

        count = subs.count()
        if count == 0:
            self.stdout.write('No subscriptions with invoice usage to reset.')
            return

        for sub in subs:
            self.stdout.write(
                f'  {sub.school.name}: {sub.invoices_used_this_year} invoices '
                f'(plan: {sub.plan.name if sub.plan else "none"})'
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\nDry run: {count} subscription(s) would be reset.'
            ))
            return

        updated = subs.update(
            invoices_used_this_year=0,
            invoice_year_start=today,
        )
        self.stdout.write(self.style.SUCCESS(
            f'\nReset invoice counters for {updated} subscription(s).'
        ))
