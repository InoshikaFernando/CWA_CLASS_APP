"""
Read-only audit of Stripe subscriptions vs the local DB.

Prints how many subscriptions Stripe holds, grouped by metadata.type and
status, plus the local-DB picture, so the super-admin dashboard counts can be
reconciled against the Stripe dashboard ("20 paid students, 1 active institute").

Read-only — makes no changes. Run on an environment with the LIVE Stripe key
(prod), since test uses a sandbox key with unrelated data:

    python manage.py stripe_subscription_audit
"""
from collections import Counter

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Read-only audit of Stripe subscriptions by type + status.'

    def handle(self, *args, **options):
        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            self.stderr.write('STRIPE_SECRET_KEY not set — cannot audit.')
            return
        mode = 'TEST/sandbox' if key.startswith('sk_test') else 'LIVE'
        self.stdout.write(f'Stripe key mode: {mode}')
        stripe.api_key = key

        by_type_status = Counter()
        by_type = Counter()
        total = 0
        for s in stripe.Subscription.list(status='all', limit=100).auto_paging_iter():
            md = s.get('metadata') or {}
            t = md.get('type') or '(none)'
            by_type_status[(t, s.get('status'))] += 1
            by_type[t] += 1
            total += 1

        self.stdout.write(f'\nStripe subscriptions (all statuses): {total}')
        self.stdout.write('\nBy type + status:')
        for (t, status), n in sorted(by_type_status.items()):
            self.stdout.write(f'  {t:<16} {status:<12} {n}')

        self.stdout.write('\nBy type (total):')
        for t, n in sorted(by_type.items()):
            self.stdout.write(f'  {t:<16} {n}')

        # Dashboard buckets
        students_paid = sum(
            n for (t, st), n in by_type_status.items()
            if t in ('individual', 'school_student') and st == 'active'
        )
        institutes_paid = sum(
            n for (t, st), n in by_type_status.items()
            if t == 'institute' and st == 'active'
        )
        self.stdout.write(
            f'\nDashboard would show — paid students: {students_paid} '
            f'| active institutes: {institutes_paid}',
        )

        # Local DB comparison
        from billing.models import Subscription, SchoolSubscription
        self.stdout.write('\nLocal DB:')
        self.stdout.write(
            f'  billing.Subscription rows: {Subscription.objects.count()} '
            f'(with stripe_subscription_id: '
            f'{Subscription.objects.exclude(stripe_subscription_id="").count()})',
        )
        self.stdout.write(
            f'  SchoolSubscription rows: {SchoolSubscription.objects.count()} '
            f'(active: {SchoolSubscription.objects.filter(status="active").count()})',
        )
