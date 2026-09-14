"""
Change what a module actually charges, since a Stripe Price cannot be edited.

Editing ``ModuleProduct.price`` in the admin moves the number on every page in
the app and nothing else. The Stripe Price it points at is immutable, so the
card keeps being charged the old amount, and ``sync_stripe_prices`` will not
repair it: the row already has a price id, so the matcher reports it as
"already synced". Until this command there was no supported way to reprice a
module at all — which is how production spent months displaying $10 for three
modules that Stripe billed at $9.

What it does, per module:

1. Reads the intended price from ``ModuleProduct.price`` — the admin stays the
   place a price is decided; this only makes Stripe agree with it.
2. Creates a NEW Stripe Price for that amount on the SAME Stripe Product, so
   the product keeps its identity, metadata and history.
3. Repoints ``ModuleProduct.stripe_price_id`` at it, so every new subscriber
   is charged the intended amount.

Schools already subscribed keep the old price until they are moved, because a
subscription item holds its own price id. ``--migrate-existing`` moves them —
which is a price change for a paying customer, so it is separate, opt-in, and
listed school by school before it happens.

Dry-run by default; pass --apply to write. Stripe objects are created only
under --apply.

    python manage.py reprice_module --module teachers_attendance
    python manage.py reprice_module --drifted
    python manage.py reprice_module --drifted --apply
    python manage.py reprice_module --module teachers_attendance --apply --migrate-existing
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Repoint a module at a new Stripe price matching ModuleProduct.price.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--module', action='append', dest='modules', default=[],
            help='Module slug to reprice. Repeatable.',
        )
        parser.add_argument(
            '--drifted', action='store_true',
            help='Every active module whose Stripe amount differs from its local price.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually create the prices and save. Without it, nothing is written.',
        )
        parser.add_argument(
            '--migrate-existing', action='store_true',
            help=('Also move schools already subscribed onto the new price. This '
                  'changes what a paying customer is billed — read the list first.'),
        )

    def handle(self, *args, **options):
        import stripe
        from django.conf import settings
        from billing.models import ModuleProduct, ModuleSubscription

        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            raise CommandError('STRIPE_SECRET_KEY is not set — cannot reprice.')
        stripe.api_key = key
        apply_changes = options['apply']

        if not options['modules'] and not options['drifted']:
            raise CommandError('Pass --module <slug> (repeatable) or --drifted.')

        self.stdout.write(
            f'Stripe key mode: '
            f'{"TEST/sandbox" if key.startswith("sk_test") else "LIVE"}'
        )

        products = ModuleProduct.objects.filter(is_active=True)
        if options['modules']:
            products = products.filter(module__in=options['modules'])
            found = set(products.values_list('module', flat=True))
            missing = [m for m in options['modules'] if m not in found]
            if missing:
                raise CommandError(
                    f'No active ModuleProduct for: {", ".join(missing)}'
                )

        want_currency = (getattr(settings, 'STRIPE_CURRENCY', 'usd') or 'usd').lower()
        repriced = 0

        for mp in products.order_by('module'):
            if not mp.stripe_price_id:
                # Nothing to reprice — the module has never had a price. That is
                # a different repair, and saying so is better than creating a
                # second product alongside the one sync would have made.
                if not options['drifted']:
                    self.stdout.write(self.style.WARNING(
                        f'  {mp.name}: no Stripe price at all — run '
                        f'"sync_stripe_prices --create-missing" instead.'
                    ))
                continue

            try:
                old = stripe.Price.retrieve(mp.stripe_price_id)
            except stripe.error.StripeError as exc:
                self.stderr.write(self.style.ERROR(
                    f'  {mp.name}: cannot read {mp.stripe_price_id} — {exc}'
                ))
                continue

            old_amount = Decimal(old.unit_amount or 0) / 100
            if Decimal(mp.price) == old_amount:
                if not options['drifted']:
                    self.stdout.write(
                        f'  {mp.name}: already charges {old_amount} — nothing to do.'
                    )
                continue

            product_id = old.product if isinstance(old.product, str) else old.product.id
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'\n{mp.name} ({mp.module})'
            ))
            self.stdout.write(
                f'  charges {old_amount} {old.currency.upper()} '
                f'({mp.stripe_price_id}) -> should charge {mp.price} '
                f'{want_currency.upper()}'
            )

            if not apply_changes:
                self.stdout.write(self.style.WARNING(
                    f'  [DRY RUN] would create a new {want_currency.upper()} price '
                    f'at {mp.price} on product {product_id} and repoint this row.'
                ))
            else:
                try:
                    new_price = stripe.Price.create(
                        product=product_id,
                        unit_amount=int(Decimal(mp.price) * 100),
                        currency=want_currency,
                        recurring={'interval': 'month'},
                        metadata={'module_slug': mp.module,
                                  'replaces': mp.stripe_price_id},
                    )
                except stripe.error.StripeError as exc:
                    self.stderr.write(self.style.ERROR(
                        f'  Failed to create the new price: {exc}'
                    ))
                    continue
                mp.stripe_price_id = new_price.id
                mp.save(update_fields=['stripe_price_id'])
                self.stdout.write(self.style.SUCCESS(
                    f'  [OK] new subscribers now charged {mp.price} — {new_price.id}'
                ))

                # Archive the price we moved off. Not tidiness — correctness.
                # Both prices sit on the same Stripe product, so both answer to
                # this module's slug, and sync_stripe_prices only considers
                # ACTIVE prices. Leaving the old one active gives the next sync
                # two candidates for one module and a chance to repoint the row
                # back to the amount we just moved away from.
                #
                # Archiving does NOT stop it billing: a subscription item keeps
                # charging an archived price, which is exactly what the schools
                # left on the old amount need. It only prevents new use.
                try:
                    stripe.Price.modify(old.id, active=False)
                    self.stdout.write(
                        f'  archived the old price {old.id} so it cannot be '
                        f'matched again'
                    )
                except stripe.error.StripeError as exc:
                    # The repricing itself succeeded; say what is left undone
                    # rather than failing after the fact.
                    self.stderr.write(self.style.WARNING(
                        f'  repriced, but could not archive {old.id}: {exc}. '
                        f'Archive it in the Stripe dashboard — while it is '
                        f'active, sync_stripe_prices may repoint this module '
                        f'back to it.'
                    ))
            repriced += 1

            # Everyone already on it, and what happens to them.
            existing = (ModuleSubscription.objects
                        .filter(module=mp.module, is_active=True)
                        .exclude(stripe_subscription_item_id='')
                        .select_related('school_subscription__school'))
            if not existing:
                continue

            self.stdout.write(
                f'  {existing.count()} school(s) already subscribed at {old_amount}:'
            )
            for row in existing:
                school = row.school_subscription.school
                if not options['migrate_existing']:
                    self.stdout.write(
                        f'    {school.name} — stays at {old_amount} '
                        f'(--migrate-existing to move them)'
                    )
                    continue
                if not apply_changes:
                    self.stdout.write(self.style.WARNING(
                        f'    [DRY RUN] {school.name} — would move to {mp.price}'
                    ))
                    continue
                try:
                    # proration_behavior='none': the new amount starts at their
                    # next invoice rather than issuing a mid-cycle charge. A
                    # price rise a customer has been told about should arrive
                    # on the date they expect a bill, not as a surprise today.
                    stripe.SubscriptionItem.modify(
                        row.stripe_subscription_item_id,
                        price=mp.stripe_price_id,
                        proration_behavior='none',
                    )
                except stripe.error.StripeError as exc:
                    self.stderr.write(self.style.ERROR(
                        f'    {school.name} — FAILED, still at {old_amount}: {exc}'
                    ))
                    continue
                self.stdout.write(self.style.SUCCESS(
                    f'    {school.name} — moved to {mp.price} from their next invoice'
                ))

        self.stdout.write('')
        if not repriced:
            self.stdout.write(self.style.SUCCESS(
                'Nothing to reprice — every module charges what it displays.'
            ))
        elif not apply_changes:
            self.stdout.write(self.style.WARNING(
                f'Dry run — {repriced} module(s) would be repriced. '
                f'Nothing was created or saved. Re-run with --apply.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'{repriced} module(s) repriced.'
            ))
            if not options['migrate_existing']:
                self.stdout.write(
                    'Schools already subscribed keep the old price. Move them '
                    'with --migrate-existing once they have been told.'
                )
