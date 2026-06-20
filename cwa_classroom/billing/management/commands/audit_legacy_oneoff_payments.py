"""
Read-only audit of students hit by the legacy one-time PaymentIntent flow.

Background
----------
A deprecated PaymentIntent checkout (removed in the #499 fix) charged a card
ONCE without creating a recurring Stripe subscription or saving a card. The
victim ends up with a succeeded ``billing.Payment`` and a local
``billing.Subscription`` that is ``active`` but has an EMPTY
``stripe_subscription_id`` — so they never auto-renew, and in Stripe there is a
customer with a charge but no subscription and no saved card.

The code path is now closed, but anyone charged that way BEFORE the fix is still
sitting in the DB and must be reconciled by hand. This command finds them.

Predicate (the affected cohort)
-------------------------------
A user is flagged iff:
  * they have a ``billing.Payment`` with ``status='succeeded'``, AND
  * their ``billing.Subscription`` has an empty/NULL ``stripe_subscription_id``
    (or they have no ``Subscription`` row at all).

For each, prints: user id, username, email, last succeeded amount + date, the
local subscription status, and an MHB-cohort flag (CPP-341 — students actively
enrolled in the MHB school, default id 4).

Read-only — makes NO changes. Run on prod:

    python manage.py audit_legacy_oneoff_payments
    python manage.py audit_legacy_oneoff_payments --mhb-school 4
    python manage.py audit_legacy_oneoff_payments --stripe   # also verify vs live Stripe

``--stripe`` additionally calls the LIVE Stripe API (read-only) per affected
customer to confirm "no active subscription" and "no saved card". Omit it to
keep the audit purely DB-side.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from billing.models import Payment, Subscription


class Command(BaseCommand):
    help = (
        'Read-only audit: students charged via the legacy one-time PaymentIntent '
        'flow who have no recurring Stripe subscription (paid once, never renews).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--mhb-school', type=int, default=4, metavar='SCHOOL_ID',
            help='School id used to flag the MHB cohort (CPP-341). Default 4.',
        )
        parser.add_argument(
            '--stripe', action='store_true',
            help='Also verify each affected customer against the LIVE Stripe API '
                 '(no active subscription / no saved card). Read-only API calls.',
        )

    def handle(self, *args, **options):
        mhb_school_id = options['mhb_school']

        # Everyone with a succeeded one-off legacy Payment.
        paid_user_ids = set(
            Payment.objects.filter(status=Payment.STATUS_SUCCEEDED)
            .values_list('user_id', flat=True)
        )
        if not paid_user_ids:
            self.stdout.write(self.style.SUCCESS(
                'No succeeded billing.Payment rows exist - nobody used the legacy flow.'
            ))
            return

        # MHB cohort = students actively enrolled in the MHB school.
        from classroom.models import School, SchoolStudent
        mhb_name = ''
        school = School.objects.filter(id=mhb_school_id).first()
        if school is None:
            self.stderr.write(self.style.WARNING(
                f'No School with id={mhb_school_id} — MHB flag will be blank for all rows.'
            ))
        else:
            mhb_name = school.name
        mhb_ids = set(
            SchoolStudent.objects.filter(school_id=mhb_school_id, is_active=True)
            .values_list('student_id', flat=True)
        )

        # Affected = payer whose Subscription has no recurring Stripe subscription.
        affected = list(
            Subscription.objects
            .filter(user_id__in=paid_user_ids)
            .filter(Q(stripe_subscription_id='') | Q(stripe_subscription_id__isnull=True))
            .select_related('user', 'package')
            .order_by('user_id')
        )

        # Edge case: paid one-off but no Subscription row at all.
        users_with_sub = set(
            Subscription.objects.filter(user_id__in=paid_user_ids)
            .values_list('user_id', flat=True)
        )
        no_sub_ids = sorted(paid_user_ids - users_with_sub)

        scope = f' (MHB school = id {mhb_school_id}'
        scope += f' "{mhb_name}")' if mhb_name else ', name unknown)'
        self.stdout.write(f'Legacy one-off payment audit{scope}\n')

        if not affected and not no_sub_ids:
            self.stdout.write(self.style.SUCCESS(
                f'{len(paid_user_ids)} user(s) used the legacy flow but ALL now have a '
                'recurring stripe_subscription_id — nothing to reconcile.'
            ))
            return

        header = (
            f"{'id':>6}  {'username':<22} {'email':<32} {'amount':>9}  "
            f"{'paid_at':<16}  {'status':<10}  MHB"
        )
        self.stdout.write(header)
        self.stdout.write('-' * len(header))

        mhb_count = 0
        for sub in affected:
            u = sub.user
            p = (
                Payment.objects.filter(user=u, status=Payment.STATUS_SUCCEEDED)
                .order_by('-created_at').first()
            )
            amount = f'{p.amount}' if p else '-'
            when = p.created_at.strftime('%Y-%m-%d %H:%M') if p else '-'
            is_mhb = u.id in mhb_ids
            mhb_count += 1 if is_mhb else 0
            self.stdout.write(
                f'{u.id:>6}  {(u.username or ""):<22} {(u.email or ""):<32} '
                f'{amount:>9}  {when:<16}  {(sub.status or ""):<10}  {"YES" if is_mhb else ""}'
            )

        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            f'Affected (active local sub, no recurring stripe_subscription_id): {len(affected)} '
            f'| of which MHB: {mhb_count}'
        ))
        if no_sub_ids:
            self.stdout.write(self.style.WARNING(
                f'Paid one-off but NO Subscription row at all (user ids): {no_sub_ids}'
            ))

        if options['stripe']:
            self._verify_against_stripe(affected)

    def _verify_against_stripe(self, affected):
        """For each affected customer, confirm no active sub + no saved card (read-only)."""
        from django.conf import settings
        import stripe

        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            self.stderr.write('\nSTRIPE_SECRET_KEY not set — skipping --stripe verification.')
            return
        stripe.api_key = key
        mode = 'TEST/sandbox' if key.startswith('sk_test') else 'LIVE'
        self.stdout.write(f'\nStripe verification (key mode: {mode}):')

        for sub in affected:
            cid = sub.stripe_customer_id
            if not cid:
                self.stdout.write(f'  user {sub.user_id}: no stripe_customer_id on record')
                continue
            try:
                subs = stripe.Subscription.list(customer=cid, status='all', limit=1)
                cards = stripe.PaymentMethod.list(customer=cid, type='card', limit=1)
                n_subs = len(subs.get('data', []))
                n_cards = len(cards.get('data', []))
                flag = 'OK — confirmed orphaned' if (n_subs == 0 and n_cards == 0) else 'has sub/card — re-check'
                self.stdout.write(
                    f'  user {sub.user_id} ({cid}): subs={n_subs} cards={n_cards}  → {flag}'
                )
            except stripe.error.StripeError as e:
                self.stdout.write(f'  user {sub.user_id} ({cid}): Stripe error — {e}')
