"""
Send email warnings to schools and individual students whose trial/promo expires within N days.

Usage:
    python manage.py send_trial_expiry_warnings          # default: 3 days
    python manage.py send_trial_expiry_warnings --days 7
    python manage.py send_trial_expiry_warnings --dry-run
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from billing.models import SchoolSubscription, Subscription


class Command(BaseCommand):
    help = 'Send trial/promo expiry warning emails to schools and individual students.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=3,
            help='Warn when trial/promo expires within this many days (default: 3).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show which emails would be sent without sending them.',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        now = timezone.now()
        cutoff = now + timezone.timedelta(days=days)
        count = 0

        # ── School subscriptions ──
        expiring_school_subs = SchoolSubscription.objects.filter(
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end__isnull=False,
            trial_end__gt=now,
            trial_end__lte=cutoff,
        ).select_related('school__admin')

        for sub in expiring_school_subs:
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

        # ── Individual student subscriptions (trial or promo) ──
        expiring_individual_subs = Subscription.objects.filter(
            Q(status=Subscription.STATUS_TRIALING) | Q(status=Subscription.STATUS_ACTIVE, promo_code_used__gt=''),
            trial_end__isnull=False,
            trial_end__gt=now,
            trial_end__lte=cutoff,
        ).select_related('user')

        for sub in expiring_individual_subs:
            remaining = sub.access_days_remaining if sub.is_promo_activated else sub.trial_days_remaining
            user = sub.user
            email = user.email

            if not email:
                self.stdout.write(
                    self.style.WARNING(f'  SKIP user {user.username} — no email')
                )
                continue

            label = 'promo' if sub.is_promo_activated else 'trial'
            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Would email {email} — '
                    f'{label} ends in {remaining} day(s)'
                )
            else:
                from billing.email_utils import notify_individual_trial_expiring
                notify_individual_trial_expiring(user, remaining, is_promo=sub.is_promo_activated)
                self.stdout.write(
                    f'  Sent to {email} — {label} ends in {remaining} day(s)'
                )
            count += 1

        action = 'Would send' if dry_run else 'Sent'
        self.stdout.write(
            self.style.SUCCESS(f'{action} {count} expiry warning(s).')
        )
