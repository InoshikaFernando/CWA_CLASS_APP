"""
Backfill the missing ``stripe_customer_id`` on subscriptions.

Historically the checkout/webhook flow saved ``stripe_subscription_id`` but not
``stripe_customer_id`` (the customer was created at checkout before the local
Subscription row existed, so the id was never written back). That leaves the
in-app "Update Payment Method" billing portal unable to open for those users and
lets re-checkouts spawn duplicate Stripe customers.

This command reads the **authoritative** value straight from Stripe: for every
subscription that has a ``stripe_subscription_id`` but no ``stripe_customer_id``,
it retrieves that subscription from Stripe and stores its ``.customer``. It only
ever *fills in* the field — it never changes status, amounts, plans, or anything
that affects billing, and it makes only read-only Stripe calls.

Safe and idempotent: a second run finds fewer/none. Always preview first:

    python manage.py backfill_stripe_customer_ids --dry-run
    python manage.py backfill_stripe_customer_ids
"""
import stripe

from django.conf import settings
from django.core.management.base import BaseCommand

from billing.models import Subscription, SchoolSubscription


class Command(BaseCommand):
    help = 'Backfill Subscription/SchoolSubscription stripe_customer_id from Stripe.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change; write nothing.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Only process the first N (0 = all).')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        limit = opts['limit']
        stripe.api_key = settings.STRIPE_SECRET_KEY
        if not stripe.api_key:
            self.stderr.write(self.style.ERROR('STRIPE_SECRET_KEY is not set — aborting.'))
            return

        self.stdout.write(self.style.WARNING('DRY RUN — no writes.' if dry else 'LIVE — writing customer ids.'))

        totals = {'updated': 0, 'skipped': 0, 'errors': 0}
        for model, label in ((Subscription, 'Subscription'),
                             (SchoolSubscription, 'SchoolSubscription')):
            qs = (model.objects
                  .exclude(stripe_subscription_id='')
                  .filter(stripe_customer_id=''))
            if limit:
                qs = qs[:limit]
            n = qs.count()
            self.stdout.write(f'\n=== {label}: {n} to backfill ===')
            for obj in qs:
                who = getattr(obj, 'user_id', None) or f'school:{getattr(obj, "school_id", "?")}'
                try:
                    ss = stripe.Subscription.retrieve(obj.stripe_subscription_id)
                    customer = getattr(ss, 'customer', None)
                except stripe.error.StripeError as e:
                    totals['errors'] += 1
                    self.stderr.write(f'  ERROR {label} {who} ({obj.stripe_subscription_id}): {e}')
                    continue

                if not customer:
                    totals['skipped'] += 1
                    self.stdout.write(f'  SKIP  {label} {who}: Stripe sub has no customer')
                    continue

                self.stdout.write(f'  {"WOULD SET" if dry else "SET"} {label} {who}: {customer}')
                if not dry:
                    obj.stripe_customer_id = customer
                    obj.save(update_fields=['stripe_customer_id'])
                totals['updated'] += 1

        verb = 'would update' if dry else 'updated'
        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {verb}={totals["updated"]} skipped={totals["skipped"]} errors={totals["errors"]}'
        ))
