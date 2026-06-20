"""
Backfill the discount snapshot on existing subscriptions (CPP-XXX).

Going forward, CompleteProfileView records ``discount_code`` /
``discount_percent_snapshot`` when a code is redeemed. This one-off command
populates that snapshot for **existing** subscriptions so the HoI discount view
shows the right state for students onboarded before the feature shipped.

Inference (only rows where ``discount_percent_snapshot IS NULL``):

  * active/trialing AND empty ``stripe_subscription_id`` AND the user has NO
    succeeded ``Payment``  -> 100% free  (snapshot = 100)
  * ``stripe_subscription_id`` set AND the Stripe subscription carries a coupon
    with ``percent_off``    -> partial    (snapshot = percent_off)   [needs Stripe]
  * everything else                                                  -> leave NULL (treated as full)

The legacy-paid guard (a student who paid via the removed one-time PaymentIntent
flow is active with no Stripe sub, but DID pay) is enforced by the
"no succeeded Payment" condition — those rows are left NULL (full), never 100%.

Usage:
    python manage.py backfill_subscription_discounts --dry-run
    python manage.py backfill_subscription_discounts            # DB-only
    python manage.py backfill_subscription_discounts --with-stripe   # also detect partial coupons
"""
import logging

from django.core.management.base import BaseCommand

from billing.models import Payment, Subscription

logger = logging.getLogger(__name__)

_ACTIVE = (Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING)


class Command(BaseCommand):
    help = 'Backfill discount_percent_snapshot on existing subscriptions (CPP-XXX).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')
        parser.add_argument('--with-stripe', action='store_true',
                            help='Also query Stripe to detect partial-discount coupons.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        with_stripe = options['with_stripe']

        paid_user_ids = set(
            Payment.objects.filter(status=Payment.STATUS_SUCCEEDED)
            .values_list('user_id', flat=True)
        )

        rows = Subscription.objects.filter(discount_percent_snapshot__isnull=True)
        free_100 = partial = skipped = 0

        for sub in rows.iterator():
            new_pct = None
            if (sub.status in _ACTIVE and not sub.stripe_subscription_id
                    and sub.user_id not in paid_user_ids):
                new_pct = 100
            elif with_stripe and sub.stripe_subscription_id:
                new_pct = self._stripe_percent_off(sub.stripe_subscription_id)

            if new_pct is None:
                skipped += 1
                continue

            if new_pct >= 100:
                free_100 += 1
            else:
                partial += 1

            if not dry_run:
                sub.discount_percent_snapshot = new_pct
                sub.save(update_fields=['discount_percent_snapshot', 'updated_at'])

        verb = 'would set' if dry_run else 'set'
        self.stdout.write(self.style.SUCCESS(
            f'{verb}: {free_100} free(100%), {partial} partial; {skipped} left as full/none.'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes written.'))

    @staticmethod
    def _stripe_percent_off(stripe_sub_id):
        try:
            import stripe
            from django.conf import settings
            stripe.api_key = settings.STRIPE_SECRET_KEY
            ssub = stripe.Subscription.retrieve(stripe_sub_id)
            disc = ssub.get('discount') if isinstance(ssub, dict) else getattr(ssub, 'discount', None)
            coupon = (disc or {}).get('coupon') if disc else None
            pct = (coupon or {}).get('percent_off') if coupon else None
            return int(pct) if pct else None
        except Exception as e:
            logger.warning('Stripe lookup failed for %s: %s', stripe_sub_id, e)
            return None
