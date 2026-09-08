"""
Management command: sync_stripe_coupons

Create the missing Stripe coupon for every partial discount code that has none.

A code that is 1–99% off carries its discount into Stripe Checkout as a coupon
id. With that id blank the checkout is built with no discount at all: the
student is charged the FULL price, while the subscription records the percent
they were promised. Nothing surfaced that until now — the create-time sync
logged a warning and reported success — so codes can be sitting in this state
from any period when Stripe was unconfigured or unreachable.

This finds them and fixes them. 100%-off codes are skipped: they never reach
Stripe, so they need no coupon.

Usage:
    python manage.py sync_stripe_coupons --dry-run   # report only, no writes
    python manage.py sync_stripe_coupons             # create the coupons
"""
import logging

from django.core.management.base import BaseCommand

from billing.models import DiscountCode, InstituteDiscountCode

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create missing Stripe coupons for partial discount codes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List the codes that would be synced without writing anything.',
        )

    def _unsynced(self, model):
        """Partial (1–99%) codes with no coupon id — the overcharge set."""
        return model.objects.filter(
            stripe_coupon_id='',
            discount_percent__gt=0,
            discount_percent__lt=100,
        ).order_by('code')

    def handle(self, *args, **options):
        from billing.stripe_service import ensure_stripe_coupon, _stripe_configured

        dry_run = options['dry_run']
        groups = [
            ('Student (DiscountCode)', self._unsynced(DiscountCode)),
            ('Institute (InstituteDiscountCode)', self._unsynced(InstituteDiscountCode)),
        ]

        total = sum(qs.count() for _, qs in groups)
        if not total:
            self.stdout.write(self.style.SUCCESS(
                'Every partial discount code already has a Stripe coupon.'
            ))
            return

        self.stdout.write(
            f'{total} partial code(s) with no Stripe coupon — '
            f'students redeeming these are charged the full price:'
        )
        for label, qs in groups:
            for code in qs:
                active = 'active' if code.is_active else 'inactive'
                self.stdout.write(
                    f'  [{label}] {code.code} — {code.discount_percent}% off, '
                    f'{active}, {code.uses} use(s) so far'
                )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\n[DRY RUN] Nothing written. Re-run without --dry-run to create '
                'these coupons in Stripe.'
            ))
            return

        if not _stripe_configured():
            self.stderr.write(self.style.ERROR(
                'STRIPE_SECRET_KEY is not set — cannot create coupons. '
                'Nothing was changed.'
            ))
            return

        synced_count = 0
        failed = []
        for label, qs in groups:
            for code in qs:
                ok, error = ensure_stripe_coupon(code)
                if ok:
                    synced_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  synced {code.code} -> {code.stripe_coupon_id}'
                    ))
                else:
                    failed.append((code.code, error))
                    self.stderr.write(self.style.ERROR(
                        f'  FAILED {code.code}: {error}'
                    ))

        self.stdout.write(f'\nSynced {synced_count} of {total} code(s).')
        if failed:
            # Surface rather than exit 0 on a partial repair — these codes still
            # overcharge, and a green command would say otherwise.
            self.stderr.write(self.style.ERROR(
                f'{len(failed)} code(s) still have no coupon and will charge '
                f'full price: {", ".join(c for c, _ in failed)}'
            ))
