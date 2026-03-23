"""
Management command to sync Stripe Price IDs into InstitutePlan and Package records.

Fetches all active products and their prices from Stripe, then matches them
to local database records by price amount. Supports --dry-run to preview
changes before applying.

Usage:
    python manage.py sync_stripe_prices          # apply changes
    python manage.py sync_stripe_prices --dry-run # preview only
"""
import stripe
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand

from billing.models import InstitutePlan, Package


class Command(BaseCommand):
    help = 'Sync Stripe Price IDs into InstitutePlan and Package records by matching price amounts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        stripe.api_key = settings.STRIPE_SECRET_KEY

        if not stripe.api_key:
            self.stderr.write(self.style.ERROR('STRIPE_SECRET_KEY is not set.'))
            return

        self.stdout.write('Fetching products from Stripe...')

        # Fetch all active products with their default prices
        products = []
        has_more = True
        starting_after = None
        while has_more:
            params = {'active': True, 'limit': 100}
            if starting_after:
                params['starting_after'] = starting_after
            result = stripe.Product.list(**params)
            products.extend(result.data)
            has_more = result.has_more
            if result.data:
                starting_after = result.data[-1].id

        self.stdout.write(f'Found {len(products)} active products in Stripe.')

        # Fetch all prices
        prices = []
        has_more = True
        starting_after = None
        while has_more:
            params = {'active': True, 'limit': 100, 'expand': ['data.product']}
            if starting_after:
                params['starting_after'] = starting_after
            result = stripe.Price.list(**params)
            prices.extend(result.data)
            has_more = result.has_more
            if result.data:
                starting_after = result.data[-1].id

        self.stdout.write(f'Found {len(prices)} active prices in Stripe.\n')

        # Build lookup: price amount (in dollars) -> price object
        # Only recurring monthly prices for institute plans
        recurring_prices = {}
        one_time_prices = {}
        for price in prices:
            amount = Decimal(price.unit_amount) / 100  # cents -> dollars
            product_name = price.product.name if hasattr(price.product, 'name') else str(price.product)

            if price.recurring and price.recurring.interval == 'month':
                recurring_prices[amount] = {
                    'price_id': price.id,
                    'product_name': product_name,
                    'product_id': price.product.id if hasattr(price.product, 'id') else price.product,
                }
            elif not price.recurring:
                one_time_prices[amount] = {
                    'price_id': price.id,
                    'product_name': product_name,
                    'product_id': price.product.id if hasattr(price.product, 'id') else price.product,
                }

        # Sync InstitutePlan records
        institute_plans = InstitutePlan.objects.filter(is_active=True)
        updated_plans = 0
        skipped_plans = 0

        self.stdout.write(self.style.MIGRATE_HEADING('=== Institute Plans ==='))
        for plan in institute_plans:
            match = recurring_prices.get(plan.price)
            if match:
                old_id = plan.stripe_price_id
                if old_id == match['price_id']:
                    self.stdout.write(
                        f"  {plan.name} (${plan.price}/mo) — already synced: {match['price_id']}"
                    )
                    skipped_plans += 1
                    continue

                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f"  [DRY RUN] {plan.name} (${plan.price}/mo) — "
                        f"would set stripe_price_id to {match['price_id']} "
                        f"(from Stripe product: {match['product_name']})"
                    ))
                else:
                    plan.stripe_price_id = match['price_id']
                    plan.save(update_fields=['stripe_price_id'])
                    self.stdout.write(self.style.SUCCESS(
                        f"  [OK] {plan.name} (${plan.price}/mo) — "
                        f"set stripe_price_id={match['price_id']} "
                        f"(from: {match['product_name']})"
                    ))
                updated_plans += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f"  [MISS] {plan.name} (${plan.price}/mo) — "
                    f"no matching Stripe recurring monthly price found"
                ))

        # Sync Package records (individual student packages)
        packages = Package.objects.filter(is_active=True)
        updated_packages = 0
        skipped_packages = 0

        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Individual Packages ==='))
        for pkg in packages:
            if pkg.is_free:
                self.stdout.write(f"  {pkg.name} — free, skipping")
                continue

            lookup = recurring_prices if pkg.billing_type == 'recurring' else one_time_prices
            match = lookup.get(pkg.price)
            if match:
                old_id = pkg.stripe_price_id
                if old_id == match['price_id']:
                    self.stdout.write(
                        f"  {pkg.name} (${pkg.price}) — already synced: {match['price_id']}"
                    )
                    skipped_packages += 1
                    continue

                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f"  [DRY RUN] {pkg.name} (${pkg.price}) — "
                        f"would set stripe_price_id to {match['price_id']} "
                        f"(from Stripe product: {match['product_name']})"
                    ))
                else:
                    pkg.stripe_price_id = match['price_id']
                    pkg.save(update_fields=['stripe_price_id'])
                    self.stdout.write(self.style.SUCCESS(
                        f"  [OK] {pkg.name} (${pkg.price}) — "
                        f"set stripe_price_id={match['price_id']} "
                        f"(from: {match['product_name']})"
                    ))
                updated_packages += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f"  [MISS] {pkg.name} (${pkg.price}) — "
                    f"no matching Stripe price found"
                ))

        # Summary
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Summary ==='))
        action = 'would update' if dry_run else 'updated'
        self.stdout.write(f"  Institute Plans: {action} {updated_plans}, skipped {skipped_plans}")
        self.stdout.write(f"  Packages: {action} {updated_packages}, skipped {skipped_packages}")

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run — no changes saved. Run without --dry-run to apply.'))
