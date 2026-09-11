"""
Find paid modules a school has switched on that nobody is charging for.

This exists because it happened. A paying institute ran AI Grading
Professional — $49/mo list — for months and it never appeared on a single
Stripe invoice. Nothing reported it: the module was active, the pages worked,
the dashboard showed it, and the only place the truth was visible was a Stripe
invoice read by a human.

The cause is a module row with no ``stripe_price_id``. ModuleToggleView cannot
add a subscription item without one, so it falls through to activating the
module locally — the branch that is correct for a trialing school and silently
free for a paying one. That branch now warns (see billing/views.py), but a
warning only helps the next school; the ones already given away need finding.

The detection is pure DB and needs no Stripe call: a module that is genuinely
billed carries the ``stripe_subscription_item_id`` returned when the item was
created. Active + priced + on a Stripe subscription + no item id = free.

    python manage.py audit_unbilled_modules
    python manage.py audit_unbilled_modules --verify-stripe

``--verify-stripe`` additionally asks Stripe which items the subscription
actually holds, which catches the opposite drift: a local item id pointing at
an item that has since been deleted in the Stripe dashboard.

Read-only. Makes no changes, in either mode — deciding whether to backdate a
charge, comp the module, or start billing it is a commercial call, not this
command's.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Report active paid modules that are not billed in Stripe (read-only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verify-stripe', action='store_true',
            help='Also check each local subscription item id still exists in Stripe.',
        )

    def handle(self, *args, **options):
        from billing.models import ModuleProduct, ModuleSubscription

        prices = {
            p.module: p
            for p in ModuleProduct.objects.filter(is_active=True)
        }

        # Only schools that actually pay us. A trialing or comped school has no
        # stripe_subscription_id and is *supposed* to hold modules for free.
        rows = (ModuleSubscription.objects
                .filter(is_active=True)
                .exclude(school_subscription__stripe_subscription_id='')
                .select_related('school_subscription__school')
                .order_by('school_subscription__school__name', 'module'))

        unbilled, monthly_loss = [], 0
        for row in rows:
            product = prices.get(row.module)
            if product is None or product.price <= 0:
                continue  # free module, or one we no longer sell
            if row.stripe_subscription_item_id:
                continue
            unbilled.append((row, product))
            monthly_loss += product.price

        if not unbilled:
            self.stdout.write(self.style.SUCCESS(
                'No unbilled modules — every active paid module on a paying '
                'school has a Stripe subscription item.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'{len(unbilled)} active paid module(s) are NOT being billed:'
            ))
            for row, product in unbilled:
                school = row.school_subscription.school
                has_price = 'no stripe_price_id' if not product.stripe_price_id \
                    else 'price exists, item never created'
                self.stdout.write(
                    f'  {school.name} (school {school.id}) — {product.name} '
                    f'${product.price}/mo — {has_price}'
                )
            self.stdout.write(self.style.ERROR(
                f'\nUnbilled recurring revenue: ${monthly_loss}/mo'
            ))
            self.stdout.write(
                'Fix: "manage.py sync_stripe_prices --create-missing" to give '
                'the module a Stripe price, then switch the module off and on '
                'again for the school so the subscription item is created. '
                'Whether to charge for the months already given away is a '
                'commercial decision.'
            )

        if options['verify_stripe']:
            self._verify_stripe(rows, prices)

    def _verify_stripe(self, rows, prices):
        import stripe
        from django.conf import settings

        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            self.stderr.write('STRIPE_SECRET_KEY not set — cannot verify against Stripe.')
            return
        stripe.api_key = key
        self.stdout.write(
            f'\nVerifying against Stripe '
            f'({"TEST/sandbox" if key.startswith("sk_test") else "LIVE"})...'
        )

        stale = 0
        for row in rows:
            if not row.stripe_subscription_item_id:
                continue
            product = prices.get(row.module)
            if product is None or product.price <= 0:
                continue
            try:
                stripe.SubscriptionItem.retrieve(row.stripe_subscription_item_id)
            except stripe.error.InvalidRequestError:
                stale += 1
                school = row.school_subscription.school
                self.stdout.write(self.style.ERROR(
                    f'  {school.name} (school {school.id}) — {product.name}: '
                    f'item {row.stripe_subscription_item_id} no longer exists '
                    f'in Stripe, so it is active locally and unbilled.'
                ))
            except stripe.error.StripeError as exc:
                # Never report a network hiccup as a billing hole.
                self.stderr.write(
                    f'  could not check item {row.stripe_subscription_item_id}: {exc}'
                )

        if not stale:
            self.stdout.write(self.style.SUCCESS(
                '  Every local subscription item id still exists in Stripe.'
            ))
