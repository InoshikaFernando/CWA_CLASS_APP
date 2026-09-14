"""
Narrow a discount code to the products it was meant for.

A Stripe coupon's ``applies_to`` is fixed at creation, so a code synced before
scopes existed is unscoped forever: it discounts the institute's plan, every
add-on module, and every module they buy afterwards. EARLYBIRD in production is
50% off, unscoped, ``duration=forever`` — on a school holding $315/mo of
product that is $157.50 a month, growing with every module they add.

Unscoped also blocks everything else. Two subscription discounts reaching the
same line compound (two 50% coupons take 75% off, not 50%), so an unscoped
coupon makes every other offer unaddable — which is why a school on EARLYBIRD
could never receive the AI import introductory price the plans page promises.

This mints a NEW coupon at the code's current scope and points the code at it.
Existing subscriptions keep the coupon they carry until they are moved, because
swapping one is a price rise for a paying customer: ``--migrate-existing`` does
that, listing every school before it acts.

Dry-run by default; --apply to write.

    python manage.py rescope_discount_code EARLYBIRD
    python manage.py rescope_discount_code EARLYBIRD --apply
    python manage.py rescope_discount_code EARLYBIRD --apply --migrate-existing
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Re-create a discount code\'s Stripe coupon at its current scope.'

    def add_arguments(self, parser):
        parser.add_argument('code', help='The discount code, e.g. EARLYBIRD.')
        parser.add_argument(
            '--apply', action='store_true',
            help='Create the coupon and save. Without it, nothing is written.',
        )
        parser.add_argument(
            '--migrate-existing', action='store_true',
            help=('Also move subscriptions already on the old coupon. This '
                  'changes what paying schools are billed — read the list first.'),
        )

    def handle(self, *args, **options):
        import stripe
        from django.conf import settings
        from billing.models import DiscountCode, SchoolSubscription
        from billing.stripe_service import (
            _build_stripe_coupon_kwargs, _coupon_scope,
            subscription_discount_coupons,
        )

        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            raise CommandError('STRIPE_SECRET_KEY is not set.')
        stripe.api_key = key
        apply_changes = options['apply']

        try:
            code = DiscountCode.objects.get(code=options['code'])
        except DiscountCode.DoesNotExist:
            raise CommandError(f'No discount code "{options["code"]}".')

        self.stdout.write(
            f'Stripe key mode: '
            f'{"TEST/sandbox" if key.startswith("sk_test") else "LIVE"}'
        )
        self.stdout.write(f'{code.code}: {code.discount_percent}% off, '
                          f'scope={code.scope}, duration={code.duration}')

        old_coupon_id = code.stripe_coupon_id
        if not old_coupon_id:
            self.stdout.write(self.style.WARNING(
                'This code has no Stripe coupon yet — nothing to re-scope. '
                'Syncing it now will build it at the current scope.'
            ))
            return

        try:
            old = stripe.Coupon.retrieve(old_coupon_id)
        except stripe.error.StripeError as exc:
            raise CommandError(f'Cannot read coupon {old_coupon_id}: {exc}')

        old_scope = _coupon_scope(old)
        self.stdout.write(
            f'  current coupon {old_coupon_id}: '
            f'{"discounts EVERYTHING" if old_scope is None else ", ".join(sorted(old_scope))}'
        )

        try:
            kwargs = _build_stripe_coupon_kwargs(code)
        except ValueError as exc:
            raise CommandError(str(exc))

        new_scope = (set(kwargs['applies_to']['products'])
                     if 'applies_to' in kwargs else None)
        if new_scope == old_scope:
            self.stdout.write(self.style.SUCCESS(
                '  already at this scope — nothing to do.'
            ))
            return
        self.stdout.write(
            f'  would become: '
            f'{"EVERYTHING" if new_scope is None else ", ".join(sorted(new_scope))}'
        )

        # Everyone currently carrying the old coupon.
        affected = []
        for sub in (SchoolSubscription.objects
                    .exclude(stripe_subscription_id='')
                    .select_related('school')):
            try:
                s = stripe.Subscription.retrieve(
                    sub.stripe_subscription_id, expand=['discounts.coupon'])
            except stripe.error.StripeError as exc:
                self.stderr.write(f'  could not read {sub.stripe_subscription_id}: {exc}')
                continue
            ids = [c.get('id') if isinstance(c, dict) else getattr(c, 'id', None)
                   for c in subscription_discount_coupons(s)]
            if old_coupon_id in ids:
                affected.append((sub, s, ids))

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\n  [DRY RUN] no coupon created, nothing moved.'))
            self._report(affected, old_coupon_id, migrate=options['migrate_existing'])
            return

        try:
            new_coupon = stripe.Coupon.create(**kwargs)
        except stripe.error.StripeError as exc:
            raise CommandError(f'Could not create the scoped coupon: {exc}')
        new_id = (new_coupon.get('id') if isinstance(new_coupon, dict)
                  else new_coupon.id)
        code.stripe_coupon_id = new_id
        code.save(update_fields=['stripe_coupon_id'])
        self.stdout.write(self.style.SUCCESS(
            f'  [OK] new coupon {new_id} — new checkouts use it.'))

        self._report(affected, old_coupon_id, migrate=options['migrate_existing'])
        if not options['migrate_existing']:
            return

        for sub, s, ids in affected:
            swapped = [new_id if i == old_coupon_id else i for i in ids]
            try:
                stripe.Subscription.modify(
                    sub.stripe_subscription_id,
                    discounts=[{'coupon': c} for c in swapped],
                )
            except stripe.error.StripeError as exc:
                self.stderr.write(self.style.ERROR(
                    f'    {sub.school.name} — FAILED, still on {old_coupon_id}: {exc}'))
                continue
            self.stdout.write(self.style.SUCCESS(
                f'    {sub.school.name} — moved to {new_id}'))

    def _report(self, affected, old_coupon_id, migrate):
        if not affected:
            self.stdout.write('\n  No subscription currently carries this coupon.')
            return
        self.stdout.write(
            f'\n  {len(affected)} subscription(s) on {old_coupon_id}:')
        for sub, _s, _ids in affected:
            note = ('would be moved — THIS CHANGES THEIR BILL' if migrate
                    else 'stays on the old coupon (--migrate-existing to move)')
            self.stdout.write(f'    {sub.school.name} — {note}')
