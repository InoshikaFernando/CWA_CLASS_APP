"""
Reset ONE student onto a clean recurring-payment path as an individual student.

Background
----------
The deprecated PaymentIntent checkout (removed in the #499 fix, see
``audit_legacy_oneoff_payments``) charged a card ONCE without creating a
recurring Stripe subscription and without saving a card. The victim is left
with:

  * a succeeded ``billing.Payment``, and
  * a local ``billing.Subscription`` that is ``active`` but has an EMPTY
    ``stripe_subscription_id``.

So they keep app access forever off a single charge and never auto-renew.
``reconcile_subscription`` cannot help — it syncs FROM Stripe, and in Stripe
there is no subscription to sync. The only fix is to reset the local state so
the student walks back through the *current* Checkout flow (subscription mode),
which creates a real recurring subscription that the webhook links back.

What this does
--------------
For the named user, in one transaction:

  1. (``--make-individual``) swap ``Role.STUDENT`` -> ``Role.INDIVIDUAL_STUDENT``
     so they are billed as an individual rather than riding a school plan.
  2. Cancel the stale local ``Subscription`` (status -> cancelled, ``cancelled_at``
     stamped). ``stripe_customer_id`` is KEPT so the next checkout reuses the
     same Stripe customer instead of creating a duplicate.
  3. Re-gate only where a gate exists: a school student gets
     ``profile_completed=False`` (``ProfileCompletionMiddleware`` sends them to
     the CompleteProfileView payment gate). An individual student is left alone —
     ``TrialExpiryMiddleware`` already routes a non-active subscription to the
     ``trial_expired`` payment wall, and CompleteProfileView has no payment
     branch for individuals.

Succeeded ``billing.Payment`` rows are NEVER touched — they are the financial
record of what the student actually paid. Refunding or crediting the original
one-off charge is a separate business decision, made in Stripe.

Safety
------
Dry-run by default; ``--apply`` writes. Refuses to run when Stripe shows a live
active/trialing subscription for the customer (that is a
``reconcile_subscription`` job, not a reset) unless ``--force`` is passed.
Idempotent: a second run reports "already reset" and changes nothing.

Usage
-----
    python manage.py reset_individual_billing --email sihali@example.com
    python manage.py reset_individual_billing --email sihali@example.com --apply
    python manage.py reset_individual_billing --username sihali --make-individual --apply

After a successful run the student logs in, is sent to the payment wall, pays via
Stripe Checkout (subscription mode), and the webhook writes back a real
``stripe_subscription_id`` that renews.
"""
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Reset one student (legacy one-off charge) onto a real recurring '
        'subscription as an individual student. Dry-run unless --apply.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--email', help='Local user email (case-insensitive).')
        parser.add_argument('--username', help='Local username (case-insensitive).')
        parser.add_argument(
            '--make-individual', action='store_true',
            help='Also swap Role.STUDENT -> Role.INDIVIDUAL_STUDENT.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command is a dry run.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Reset even if Stripe reports a live active/trialing subscription. '
                 'Use only when you have confirmed that subscription is not this user\'s.',
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _resolve_user(self, email, username):
        from accounts.models import CustomUser

        if bool(email) == bool(username):
            raise CommandError('Provide exactly one of --email or --username.')

        if email:
            matches = list(CustomUser.objects.filter(email__iexact=email))
            label = f'email {email}'
        else:
            matches = list(CustomUser.objects.filter(username__iexact=username))
            label = f'username {username}'

        if not matches:
            raise CommandError(f'No user with {label}.')
        if len(matches) > 1:
            ids = ', '.join(str(u.id) for u in matches)
            raise CommandError(
                f'{len(matches)} users share {label} (ids: {ids}). '
                'Re-run with --username to pick one.'
            )
        return matches[0]

    @staticmethod
    def _subscription_or_none(user):
        from billing.models import Subscription
        try:
            return user.subscription
        except Subscription.DoesNotExist:
            return None

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _report_state(self, user, sub):
        from billing.models import Payment

        roles = ', '.join(
            user.roles.filter(is_active=True).values_list('name', flat=True)
        ) or 'none'
        self.stdout.write(f'User #{user.id} {user.username} <{user.email or "no email"}>')
        self.stdout.write(f'  roles              : {roles}')
        self.stdout.write(f'  profile_completed  : {user.profile_completed}')

        if sub is None:
            self.stdout.write('  subscription       : NONE')
        else:
            self.stdout.write(
                f'  subscription       : status={sub.status} '
                f'package={sub.package} '
                f'stripe_sub={sub.stripe_subscription_id or "EMPTY"} '
                f'stripe_customer={sub.stripe_customer_id or "EMPTY"}'
            )

        payments = list(
            Payment.objects.filter(user=user, status=Payment.STATUS_SUCCEEDED)
            .order_by('-created_at')[:5]
        )
        if payments:
            self.stdout.write(f'  succeeded payments : {len(payments)} (most recent first)')
            for p in payments:
                self.stdout.write(
                    f'      {p.amount} on {p.created_at.strftime("%Y-%m-%d %H:%M")}'
                )
        else:
            self.stdout.write('  succeeded payments : none on record')

    # ------------------------------------------------------------------
    # Stripe guard
    # ------------------------------------------------------------------

    def _stripe_guard(self, sub, force):
        """Refuse to cancel locally while Stripe still bills this customer.

        Returns nothing; raises CommandError to stop. Skipped (loudly) when no
        Stripe key is configured or the user has no customer id.
        """
        from django.conf import settings

        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            self.stdout.write(self.style.WARNING(
                '  Stripe check       : SKIPPED (STRIPE_SECRET_KEY not set)'
            ))
            return
        if sub is None or not sub.stripe_customer_id:
            self.stdout.write(
                '  Stripe check       : skipped (no stripe_customer_id on record)'
            )
            return

        import stripe
        stripe.api_key = key
        mode = 'TEST/sandbox' if key.startswith('sk_test') else 'LIVE'
        try:
            subs = stripe.Subscription.list(
                customer=sub.stripe_customer_id, status='all', limit=100,
            )
            cards = stripe.PaymentMethod.list(
                customer=sub.stripe_customer_id, type='card', limit=1,
            )
        except Exception as e:  # noqa: BLE001 — never guess when Stripe is unreachable
            raise CommandError(
                f'Stripe lookup failed for customer {sub.stripe_customer_id}: {e}. '
                'Re-run once Stripe is reachable, or pass --force if you have '
                'verified the customer state by hand.'
            ) from e

        live = [
            s for s in subs.get('data', [])
            if s.get('status') in ('active', 'trialing', 'past_due')
        ]
        n_cards = len(cards.get('data', []))
        self.stdout.write(
            f'  Stripe check ({mode}) : live subs={len(live)} saved cards={n_cards}'
        )
        if live and not force:
            ids = ', '.join(s.get('id', '?') for s in live)
            raise CommandError(
                f'Stripe still has {len(live)} live subscription(s) for this customer '
                f'({ids}). This is NOT the legacy one-off case — run '
                '"manage.py reconcile_subscription --email ... --apply" to sync the '
                'local row instead. Pass --force only to override deliberately.'
            )
        if live and force:
            self.stdout.write(self.style.WARNING(
                '  --force: proceeding despite live Stripe subscription(s).'
            ))

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        from accounts.models import Role, UserRole
        from billing.models import Subscription

        apply_changes = opts['apply']
        make_individual = opts['make_individual']

        user = self._resolve_user(opts.get('email'), opts.get('username'))
        sub = self._subscription_or_none(user)

        self.stdout.write('Current state')
        self.stdout.write('-------------')
        self._report_state(user, sub)
        self.stdout.write('')

        self._stripe_guard(sub, opts['force'])

        # ---- work out the plan -------------------------------------------
        actions = []

        has_student_role = user.has_role(Role.STUDENT)
        is_individual = user.has_role(Role.INDIVIDUAL_STUDENT)
        if make_individual and has_student_role:
            actions.append('role: STUDENT -> INDIVIDUAL_STUDENT')
        elif make_individual and is_individual:
            self.stdout.write('  role already INDIVIDUAL_STUDENT — no swap needed.')

        if sub is None:
            self.stdout.write(self.style.WARNING(
                '  No Subscription row — nothing to cancel. The student will be '
                'gated by TrialExpiryMiddleware ("no subscription") already.'
            ))
        elif sub.status in (Subscription.STATUS_CANCELLED, Subscription.STATUS_EXPIRED):
            self.stdout.write(
                f'  subscription already {sub.status} — no cancel needed.'
            )
        else:
            actions.append(f'subscription: {sub.status} -> cancelled')

        # Re-gate only a school student: CompleteProfileView's payment branch is
        # school-student only, so flipping the flag for an individual would add a
        # dead step rather than a payment gate.
        will_be_individual = is_individual or (make_individual and has_student_role)
        if not will_be_individual and has_student_role and user.profile_completed:
            actions.append('profile_completed: True -> False (re-gate at CompleteProfileView)')

        if not actions:
            self.stdout.write(self.style.SUCCESS(
                '\nNothing to do — this account is already reset.'
            ))
            return

        self.stdout.write('\nPlanned changes')
        self.stdout.write('---------------')
        for a in actions:
            self.stdout.write(f'  * {a}')

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\nDry run — nothing written. Re-run with --apply to commit.'
            ))
            return

        # ---- apply --------------------------------------------------------
        with transaction.atomic():
            if make_individual and has_student_role:
                student_role = Role.objects.filter(name=Role.STUDENT).first()
                indv_role, _ = Role.objects.get_or_create(
                    name=Role.INDIVIDUAL_STUDENT,
                    defaults={'display_name': 'Individual Student'},
                )
                UserRole.objects.filter(user=user, role=student_role).delete()
                UserRole.objects.get_or_create(user=user, role=indv_role)

            if sub is not None and sub.status not in (
                Subscription.STATUS_CANCELLED, Subscription.STATUS_EXPIRED,
            ):
                sub.status = Subscription.STATUS_CANCELLED
                sub.cancelled_at = timezone.now()
                sub.cancel_at_period_end = False
                # stripe_customer_id deliberately preserved — the next checkout
                # reuses the same Stripe customer.
                sub.save(update_fields=[
                    'status', 'cancelled_at', 'cancel_at_period_end', 'updated_at',
                ])

            if not will_be_individual and has_student_role and user.profile_completed:
                user.profile_completed = False
                user.save(update_fields=['profile_completed'])

        logger.info(
            'reset_individual_billing applied for user %s (%s): %s',
            user.id, user.email, '; '.join(actions),
        )
        self.stdout.write(self.style.SUCCESS('\nApplied.'))
        self.stdout.write(
            'Next: the student logs in, is routed to the payment wall, and pays '
            'through Stripe Checkout (subscription mode). The checkout webhook '
            'writes back a real stripe_subscription_id that renews monthly.'
        )
        self.stdout.write(
            'The original one-off charge is untouched — refund or credit it in '
            'Stripe if that was agreed.'
        )
