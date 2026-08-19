"""
Reconcile a local individual Subscription against Stripe's authoritative status.

Fixes the "paid in Stripe but still walled off in the app" case: a successful
checkout whose activation webhook never processed leaves the local
Subscription.status stale (expired/past_due), so TrialExpiryMiddleware keeps
gating the student even though Stripe holds an active subscription.

Reads the truth from Stripe and syncs the local row. Dry-run by default;
pass --apply to write. Idempotent.

Usage:
    python manage.py reconcile_subscription --email ratnayakehimali+sanduli@yahoo.com
    python manage.py reconcile_subscription --email x@y.com --apply
    python manage.py reconcile_subscription --stripe-subscription-id sub_1Tt3Qq --apply
    python manage.py reconcile_subscription --all-stuck            # sweep: report only
    python manage.py reconcile_subscription --all-stuck --apply    # sweep: fix all
"""
from django.core.management.base import BaseCommand, CommandError


# Stripe status -> local Subscription status. Kept identical to the webhook
# handler (_sync_individual_subscription) so reconcile and webhook agree.
def _map_stripe_status(stripe_status):
    from billing.models import Subscription
    return {
        'active': Subscription.STATUS_ACTIVE,
        'trialing': Subscription.STATUS_TRIALING,
        'past_due': Subscription.STATUS_PAST_DUE,
        'canceled': Subscription.STATUS_CANCELLED,
        'cancelled': Subscription.STATUS_CANCELLED,
        'unpaid': Subscription.STATUS_PAST_DUE,
    }.get(stripe_status, stripe_status)


def apply_stripe_status_to_sub(sub, stripe_status, stripe_sub_id='', stripe_customer_id=''):
    """Pure, testable core: mutate a local Subscription to match Stripe.

    Returns (changed: bool, old_status, new_status). Does NOT save — the caller
    saves only under --apply, so this is safe to call in a dry run.
    """
    from django.utils import timezone
    old_status = sub.status
    new_status = _map_stripe_status(stripe_status)
    sub.status = new_status
    if stripe_sub_id:
        sub.stripe_subscription_id = stripe_sub_id
    if stripe_customer_id:
        sub.stripe_customer_id = stripe_customer_id
    from billing.models import Subscription
    if new_status == Subscription.STATUS_ACTIVE:
        sub.trial_end = None
        if not sub.current_period_start:
            sub.current_period_start = timezone.now()
    changed = old_status != new_status or True  # id/customer may also change
    return (old_status != new_status), old_status, new_status


class Command(BaseCommand):
    help = "Sync a local individual Subscription to Stripe's authoritative status."

    def add_arguments(self, parser):
        parser.add_argument('--email', help='Local user email to reconcile.')
        parser.add_argument('--stripe-subscription-id', dest='sub_id',
                            help='Reconcile the local row linked to this Stripe subscription.')
        parser.add_argument('--all-stuck', action='store_true',
                            help='Sweep: every Stripe active/trialing sub whose local row is not active.')
        parser.add_argument('--apply', action='store_true',
                            help='Write changes. Without this, dry-run only.')

    def handle(self, *args, **opts):
        import stripe
        from django.conf import settings

        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not key:
            raise CommandError('STRIPE_SECRET_KEY not set — cannot reconcile against Stripe.')
        stripe.api_key = key
        mode = 'TEST/sandbox' if key.startswith('sk_test') else 'LIVE'
        self.apply = opts['apply']
        self.stdout.write(f'Stripe key mode: {mode}   ({"APPLY" if self.apply else "DRY-RUN"})')

        if opts['all_stuck']:
            self._sweep(stripe)
        elif opts['email']:
            self._reconcile_email(stripe, opts['email'])
        elif opts['sub_id']:
            self._reconcile_sub_id(stripe, opts['sub_id'])
        else:
            raise CommandError('Provide --email, --stripe-subscription-id, or --all-stuck.')

    # -- resolution helpers -------------------------------------------------

    def _reconcile_email(self, stripe, email):
        from accounts.models import CustomUser
        from billing.models import Subscription
        user = CustomUser.objects.filter(email__iexact=email).first()
        if not user:
            raise CommandError(f'No local user with email {email}.')
        sub = Subscription.objects.filter(user=user).first()
        if not sub:
            self.stdout.write(self.style.WARNING(
                f'{email}: user #{user.id} has NO local Subscription row. '
                'A school-student sub is created on activation; reconcile by '
                '--stripe-subscription-id once you have it from Stripe.'))
            return
        stripe_sub = self._find_stripe_sub(stripe, sub, user)
        self._reconcile_one(sub, stripe_sub, label=email)

    def _reconcile_sub_id(self, stripe, sub_id):
        from billing.models import Subscription
        stripe_sub = stripe.Subscription.retrieve(sub_id)
        sub = Subscription.objects.filter(stripe_subscription_id=sub_id).first()
        if not sub:
            uid = (stripe_sub.get('metadata') or {}).get('user_id')
            if uid:
                sub = Subscription.objects.filter(user_id=uid).first()
        if not sub:
            raise CommandError(f'No local Subscription matches {sub_id} (by id or metadata user_id).')
        self._reconcile_one(sub, stripe_sub, label=sub_id)

    def _find_stripe_sub(self, stripe, sub, user):
        if sub.stripe_subscription_id:
            return stripe.Subscription.retrieve(sub.stripe_subscription_id)
        # Fall back to the customer's subscriptions, newest first.
        cust = sub.stripe_customer_id
        if not cust:
            raise CommandError(
                f'user #{user.id} has no stripe_subscription_id or stripe_customer_id; '
                'pass --stripe-subscription-id explicitly.')
        subs = stripe.Subscription.list(customer=cust, status='all', limit=10).get('data', [])
        if not subs:
            raise CommandError(f'No Stripe subscriptions for customer {cust}.')
        return subs[0]

    # -- core ---------------------------------------------------------------

    def _reconcile_one(self, sub, stripe_sub, label):
        stripe_status = stripe_sub['status'] if isinstance(stripe_sub, dict) else stripe_sub.status
        stripe_sub_id = stripe_sub['id'] if isinstance(stripe_sub, dict) else stripe_sub.id
        stripe_customer_id = (stripe_sub.get('customer') if isinstance(stripe_sub, dict)
                              else getattr(stripe_sub, 'customer', '')) or ''
        would_change, old, new = apply_stripe_status_to_sub(
            sub, stripe_status, stripe_sub_id, stripe_customer_id)

        self.stdout.write(
            f'\n{label}: local="{old}"  stripe="{stripe_status}"  ->  "{new}"'
            + ('' if would_change else '  (already in sync)'))
        if not self.apply:
            self.stdout.write(self.style.NOTICE('  dry-run — no change written. Re-run with --apply.'))
            return
        sub.save()
        # Keep the user's package pointer and profile flag consistent with activation.
        user = sub.user
        dirty = []
        if sub.package_id and user.package_id != sub.package_id:
            user.package_id = sub.package_id
            dirty.append('package')
        if not user.profile_completed:
            user.profile_completed = True
            dirty.append('profile_completed')
        if dirty:
            user.save(update_fields=dirty)
        from audit.services import log_event
        log_event(user=user, category='billing', action='subscription_reconciled_from_stripe',
                  detail={'old_status': old, 'new_status': new, 'stripe_subscription_id': stripe_sub_id})
        self.stdout.write(self.style.SUCCESS(f'  applied: {old} -> {new}'))

    def _sweep(self, stripe):
        from billing.models import Subscription
        stuck = 0
        for s in stripe.Subscription.list(status='all', limit=100).auto_paging_iter():
            md = s.get('metadata') or {}
            if md.get('type') != 'individual':
                continue
            if s['status'] not in ('active', 'trialing'):
                continue
            uid = md.get('user_id')
            sub = (Subscription.objects.filter(user_id=uid).first() if uid
                   else Subscription.objects.filter(stripe_subscription_id=s['id']).first())
            if not sub:
                continue
            if sub.status in (Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING):
                continue
            stuck += 1
            self._reconcile_one(sub, s, label=f'user #{uid} / {s["id"]}')
        self.stdout.write(self.style.SUCCESS(f'\nSweep complete: {stuck} stuck subscription(s).'))
