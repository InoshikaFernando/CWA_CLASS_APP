"""
Management command: dedupe_stripe_customers

Find people who have more than one Stripe customer, and optionally delete the
empty duplicates.

``get_or_create_customer`` used to mint a fresh Stripe customer on every call
when the local row it would persist the id to did not exist yet — which is the
normal state for a school student, who has no ``Subscription`` until checkout
succeeds. So a student retrying a failed checkout left one customer behind per
attempt. On 2026-09-07 one student retried eleven times.

Duplicates are not only untidy. A Stripe customer is currency-locked once it
carries a subscription, so having several is how one person ends up with two
currencies against their name and a later checkout dies on "You cannot combine
currencies on a single customer".

Safety: a duplicate is deleted ONLY when it has no subscriptions, no charges
and no invoices, and is not the id recorded locally. Anything with money or
history attached is reported and left alone — deleting a Stripe customer cannot
be undone.

Usage:
    python manage.py dedupe_stripe_customers              # report only
    python manage.py dedupe_stripe_customers --delete     # remove empty dupes
    python manage.py dedupe_stripe_customers --user 804   # one person
"""
from collections import defaultdict

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Report (and optionally delete) duplicate Stripe customers.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete', action='store_true',
            help='Delete duplicates that have no subscriptions, charges or invoices.',
        )
        parser.add_argument(
            '--user', type=int, default=None,
            help='Limit to one local user id.',
        )

    def handle(self, *args, **options):
        import stripe

        from billing.models import Subscription
        from billing.stripe_service import _ensure_stripe_key, _stripe_configured

        if not _stripe_configured():
            self.stderr.write(self.style.ERROR(
                'STRIPE_SECRET_KEY is not set — nothing to do.'))
            return
        _ensure_stripe_key()

        only_user = options['user']
        do_delete = options['delete']

        # Group every customer that carries a user_id by that user.
        by_user = defaultdict(list)
        for cust in stripe.Customer.list(limit=100).auto_paging_iter():
            uid = (cust.get('metadata') or {}).get('user_id')
            if not uid:
                continue
            if only_user is not None and str(uid) != str(only_user):
                continue
            by_user[str(uid)].append(cust)

        dupes = {u: cs for u, cs in by_user.items() if len(cs) > 1}
        if not dupes:
            self.stdout.write(self.style.SUCCESS(
                'No user has more than one Stripe customer.'))
            return

        # The id we hold locally must never be deleted, whatever Stripe says.
        local_ids = set(
            Subscription.objects.exclude(stripe_customer_id='')
            .values_list('stripe_customer_id', flat=True)
        )

        self.stdout.write(
            f'{len(dupes)} user(s) with duplicate Stripe customers:')
        deleted = kept = 0

        for uid, customers in sorted(dupes.items(), key=lambda kv: int(kv[0])):
            customers.sort(key=lambda c: c.get('created') or 0)
            keeper = customers[0]
            self.stdout.write(
                f'\n  user {uid}: {len(customers)} customers — '
                f'keeping oldest {keeper["id"]}'
            )
            for cust in customers[1:]:
                cid = cust['id']
                has_subs = bool((cust.get('subscriptions') or {}).get('data'))
                if not has_subs:
                    # `subscriptions` is not expanded by list(); ask directly.
                    has_subs = bool(
                        stripe.Subscription.list(customer=cid, limit=1).data)
                has_charges = bool(stripe.Charge.list(customer=cid, limit=1).data)
                has_invoices = bool(stripe.Invoice.list(customer=cid, limit=1).data)
                is_local = cid in local_ids

                blockers = []
                if has_subs:
                    blockers.append('has subscription')
                if has_charges:
                    blockers.append('has charges')
                if has_invoices:
                    blockers.append('has invoices')
                if is_local:
                    blockers.append('recorded in our database')

                if blockers:
                    kept += 1
                    self.stdout.write(self.style.WARNING(
                        f'    KEEP   {cid} — {", ".join(blockers)}'))
                    continue

                if not do_delete:
                    self.stdout.write(
                        f'    would delete {cid} (empty)')
                    continue

                try:
                    stripe.Customer.delete(cid)
                    deleted += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'    DELETED {cid} (empty)'))
                except Exception as e:  # noqa: BLE001 — reported, keep going
                    kept += 1
                    self.stderr.write(self.style.ERROR(
                        f'    FAILED to delete {cid}: {e}'))

        if do_delete:
            self.stdout.write(
                f'\nDeleted {deleted} empty duplicate(s); kept {kept} with history.')
        else:
            self.stdout.write(self.style.WARNING(
                '\nReport only — nothing deleted. Re-run with --delete to remove '
                'the empty duplicates.'))
