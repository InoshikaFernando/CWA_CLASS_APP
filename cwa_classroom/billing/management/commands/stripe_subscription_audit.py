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
        # Distinct entities (school_id / user_id) with an ACTIVE subscription.
        paid_students, paid_institutes = set(), set()
        for s in stripe.Subscription.list(status='all', limit=100).auto_paging_iter():
            md = s.get('metadata') or {}
            t = md.get('type') or '(none)'
            status = s.get('status')
            by_type_status[(t, status)] += 1
            by_type[t] += 1
            total += 1
            if status == 'active':
                if t in ('individual', 'school_student'):
                    paid_students.add(md.get('user_id') or s.get('id'))
                elif t == 'institute':
                    paid_institutes.add(md.get('school_id') or s.get('id'))

        self.stdout.write(f'\nStripe subscriptions (all statuses): {total}')
        self.stdout.write('\nBy type + status:')
        for (t, status), n in sorted(by_type_status.items()):
            self.stdout.write(f'  {t:<16} {status:<12} {n}')

        self.stdout.write('\nBy type (total):')
        for t, n in sorted(by_type.items()):
            self.stdout.write(f'  {t:<16} {n}')

        # Dashboard shows DISTINCT entities (deduped by school_id / user_id).
        active_sub_students = sum(
            n for (t, st), n in by_type_status.items()
            if t in ('individual', 'school_student') and st == 'active'
        )
        active_sub_institutes = sum(
            n for (t, st), n in by_type_status.items()
            if t == 'institute' and st == 'active'
        )
        self.stdout.write(
            f'\nDashboard would show — paid students: {len(paid_students)} '
            f'(distinct of {active_sub_students} active subs) '
            f'| paid institutes: {len(paid_institutes)} '
            f'(distinct of {active_sub_institutes} active subs)',
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
