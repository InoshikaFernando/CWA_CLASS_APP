"""
Send email warnings to schools whose trial expires within N days.

Usage:
    python manage.py send_trial_expiry_warnings          # default: 3 days
    python manage.py send_trial_expiry_warnings --days 7
    python manage.py send_trial_expiry_warnings --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import SchoolSubscription


class Command(BaseCommand):
    help = 'Send trial expiry warning emails to schools whose trial ends soon.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=3,
            help='Warn schools whose trial expires within this many days (default: 3).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show which emails would be sent without sending them.',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        now = timezone.now()

        expiring_subs = SchoolSubscription.objects.filter(
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end__isnull=False,
            trial_end__gt=now,
            trial_end__lte=now + timezone.timedelta(days=days),
        ).select_related('school__admin')

        count = 0
        for sub in expiring_subs:
            days_remaining = sub.trial_days_remaining
            school = sub.school
            admin_email = school.admin.email if school.admin else None

            if not admin_email:
                self.stdout.write(
                    self.style.WARNING(f'  SKIP {school.name} — no admin email')
                )
                continue

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Would email {admin_email} for '
                    f'{school.name} ({days_remaining} days left)'
                )
            else:
                from billing.email_utils import notify_trial_expiring
                notify_trial_expiring(school, days_remaining)
                self.stdout.write(
                    f'  Sent to {admin_email} for {school.name} '
                    f'({days_remaining} days left)'
                )
            count += 1

        action = 'Would send' if dry_run else 'Sent'
        self.stdout.write(
            self.style.SUCCESS(f'{action} {count} trial expiry warning(s).')
        )
