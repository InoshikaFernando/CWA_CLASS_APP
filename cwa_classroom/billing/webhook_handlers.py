"""
Stripe webhook event handlers.

Each handler processes a specific Stripe event type and updates
the local database accordingly. All handlers are idempotent.
"""
import logging
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)


def _ts_to_dt(timestamp):
    """Convert Stripe Unix timestamp to timezone-aware datetime."""
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


# ---------------------------------------------------------------------------
# checkout.session.completed
# ---------------------------------------------------------------------------

def handle_checkout_completed(event_data):
    """
    Activate subscription after successful Stripe Checkout.
    Works for individual students, school students, and institutes.
    """
    session = event_data['object']
    metadata = session.get('metadata', {})
    sub_type = metadata.get('type', '')
    stripe_subscription_id = session.get('subscription', '')

    if sub_type == 'institute':
        _activate_institute_from_checkout(metadata, stripe_subscription_id)
    elif sub_type in ('individual', 'school_student'):
        _activate_individual_from_checkout(metadata, stripe_subscription_id)
    else:
        logger.warning('Unknown checkout type: %s', sub_type)


def _activate_institute_from_checkout(metadata, stripe_subscription_id):
    from billing.models import SchoolSubscription, InstitutePlan
    from classroom.models import School

    school_id = metadata.get('school_id')
    plan_id = metadata.get('plan_id')
    if not school_id:
        return

    try:
        school = School.objects.get(id=school_id)
    except School.DoesNotExist:
        logger.error('School %s not found', school_id)
        return

    plan = InstitutePlan.objects.filter(id=plan_id).first()

    # Get or create subscription — handles schools created before billing system
    try:
        sub = school.subscription
    except SchoolSubscription.DoesNotExist:
        logger.info('Creating SchoolSubscription for existing school %s', school_id)
        sub = SchoolSubscription(school=school)
        if plan:
            sub.plan = plan

    sub.status = SchoolSubscription.STATUS_ACTIVE
    sub.stripe_subscription_id = stripe_subscription_id or sub.stripe_subscription_id
    sub.stripe_customer_id = sub.stripe_customer_id or ''
    sub.trial_end = None
    sub.current_period_start = timezone.now()
    if plan:
        sub.plan = plan
    sub.save()
    logger.info('Institute subscription activated: school=%s plan=%s', school_id, plan)


def _activate_individual_from_checkout(metadata, stripe_subscription_id):
    from billing.models import Subscription
    from accounts.models import CustomUser

    user_id = metadata.get('user_id')
    package_id = metadata.get('package_id')
    if not user_id:
        return

    try:
        user = CustomUser.objects.get(id=user_id)
        sub = user.subscription
    except (CustomUser.DoesNotExist, Subscription.DoesNotExist):
        logger.error('User %s or subscription not found', user_id)
        return

    from billing.models import Package
    package = Package.objects.filter(id=package_id).first() if package_id else sub.package

    sub.stripe_subscription_id = stripe_subscription_id or sub.stripe_subscription_id
    if package:
        sub.package = package
        user.package = package
        user.save(update_fields=['package'])

    # Check actual Stripe subscription status to respect trial period
    stripe_status = None
    if stripe_subscription_id:
        try:
            import stripe
            stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
            stripe_status = stripe_sub.status
        except Exception:
            pass

    if stripe_status == 'trialing':
        sub.status = Subscription.STATUS_TRIALING
        # Get trial_end from Stripe subscription
        try:
            from datetime import datetime
            if stripe_sub.trial_end:
                sub.trial_end = timezone.make_aware(
                    datetime.fromtimestamp(stripe_sub.trial_end),
                    timezone.utc,
                )
        except Exception:
            pass
        sub.current_period_start = timezone.now()
        sub.save()
        logger.info('Individual subscription trialing: user=%s package=%s trial_end=%s', user_id, package, sub.trial_end)
    else:
        sub.status = Subscription.STATUS_ACTIVE
        sub.trial_end = None
        sub.current_period_start = timezone.now()
        sub.save()
        logger.info('Individual subscription activated: user=%s package=%s', user_id, package)


# ---------------------------------------------------------------------------
# customer.subscription.updated
# ---------------------------------------------------------------------------

def handle_subscription_updated(event_data):
    """Sync subscription status changes from Stripe."""
    stripe_sub = event_data['object']
    stripe_sub_id = stripe_sub['id']
    status = stripe_sub['status']
    metadata = stripe_sub.get('metadata', {})

    sub_type = metadata.get('type', '')
    cancel_at_period_end = stripe_sub.get('cancel_at_period_end', False)
    current_period_start = _ts_to_dt(stripe_sub.get('current_period_start'))
    current_period_end = _ts_to_dt(stripe_sub.get('current_period_end'))

    if sub_type == 'institute':
        _sync_institute_subscription(
            stripe_sub_id, status, metadata,
            cancel_at_period_end, current_period_start, current_period_end,
        )
    elif sub_type == 'individual':
        _sync_individual_subscription(
            stripe_sub_id, status, metadata,
            cancel_at_period_end, current_period_start, current_period_end,
        )
    else:
        # Try to find by stripe_subscription_id
        _sync_by_stripe_id(
            stripe_sub_id, status,
            cancel_at_period_end, current_period_start, current_period_end,
        )


def _sync_institute_subscription(stripe_sub_id, status, metadata,
                                  cancel_at_period_end, period_start, period_end):
    from billing.models import SchoolSubscription

    STATUS_MAP = {
        'active': SchoolSubscription.STATUS_ACTIVE,
        'trialing': SchoolSubscription.STATUS_TRIALING,
        'past_due': SchoolSubscription.STATUS_PAST_DUE,
        'canceled': SchoolSubscription.STATUS_CANCELLED,
        'cancelled': SchoolSubscription.STATUS_CANCELLED,
        'unpaid': SchoolSubscription.STATUS_PAST_DUE,
    }

    school_id = metadata.get('school_id')
    try:
        sub = SchoolSubscription.objects.get(school_id=school_id)
    except SchoolSubscription.DoesNotExist:
        try:
            sub = SchoolSubscription.objects.get(stripe_subscription_id=stripe_sub_id)
        except SchoolSubscription.DoesNotExist:
            # Auto-create for schools that existed before billing system
            if school_id:
                from classroom.models import School
                try:
                    school = School.objects.get(id=school_id)
                    sub = SchoolSubscription(school=school)
                    logger.info('Auto-creating SchoolSubscription for school %s', school_id)
                except School.DoesNotExist:
                    logger.warning('No School found for id %s', school_id)
                    return
            else:
                logger.warning('No SchoolSubscription found for stripe_sub %s', stripe_sub_id)
                return

    sub.status = STATUS_MAP.get(status, status)
    sub.stripe_subscription_id = stripe_sub_id
    sub.cancel_at_period_end = cancel_at_period_end
    if period_start:
        sub.current_period_start = period_start
    if period_end:
        sub.current_period_end = period_end
    if status in ('canceled', 'cancelled'):
        sub.cancel_at_period_end = False
    sub.save()
    logger.info('Institute subscription synced: school=%s status=%s', sub.school_id, sub.status)

    # Send cancellation email
    if status in ('canceled', 'cancelled'):
        try:
            from billing.email_utils import notify_subscription_cancelled
            notify_subscription_cancelled(school=sub.school)
        except Exception:
            logger.exception('Failed to send cancellation email for school %s', sub.school_id)


def _sync_individual_subscription(stripe_sub_id, status, metadata,
                                   cancel_at_period_end, period_start, period_end):
    from billing.models import Subscription

    STATUS_MAP = {
        'active': Subscription.STATUS_ACTIVE,
        'trialing': Subscription.STATUS_TRIALING,
        'past_due': Subscription.STATUS_PAST_DUE,
        'canceled': Subscription.STATUS_CANCELLED,
        'cancelled': Subscription.STATUS_CANCELLED,
        'unpaid': Subscription.STATUS_PAST_DUE,
    }

    user_id = metadata.get('user_id')
    try:
        sub = Subscription.objects.get(user_id=user_id)
    except Subscription.DoesNotExist:
        try:
            sub = Subscription.objects.get(stripe_subscription_id=stripe_sub_id)
        except Subscription.DoesNotExist:
            logger.warning('No Subscription found for stripe_sub %s', stripe_sub_id)
            return

    sub.status = STATUS_MAP.get(status, status)
    sub.stripe_subscription_id = stripe_sub_id
    sub.cancel_at_period_end = cancel_at_period_end
    if period_start:
        sub.current_period_start = period_start
    if period_end:
        sub.current_period_end = period_end
    if status in ('canceled', 'cancelled'):
        sub.cancelled_at = timezone.now()
    sub.save()
    logger.info('Individual subscription synced: user=%s status=%s', sub.user_id, sub.status)


def _sync_by_stripe_id(stripe_sub_id, status, cancel_at_period_end, period_start, period_end):
    """Fallback: try to find subscription by stripe_subscription_id."""
    from billing.models import SchoolSubscription, Subscription

    try:
        sub = SchoolSubscription.objects.get(stripe_subscription_id=stripe_sub_id)
        _sync_institute_subscription(
            stripe_sub_id, status, {'school_id': sub.school_id},
            cancel_at_period_end, period_start, period_end,
        )
        return
    except SchoolSubscription.DoesNotExist:
        pass

    try:
        sub = Subscription.objects.get(stripe_subscription_id=stripe_sub_id)
        _sync_individual_subscription(
            stripe_sub_id, status, {'user_id': sub.user_id},
            cancel_at_period_end, period_start, period_end,
        )
        return
    except Subscription.DoesNotExist:
        pass

    logger.warning('No subscription found for stripe_sub_id %s', stripe_sub_id)


# ---------------------------------------------------------------------------
# customer.subscription.deleted
# ---------------------------------------------------------------------------

def handle_subscription_deleted(event_data):
    """Mark subscription as cancelled when Stripe deletes it."""
    stripe_sub = event_data['object']
    stripe_sub_id = stripe_sub['id']
    metadata = stripe_sub.get('metadata', {})

    # Reuse the update handler with 'canceled' status
    event_data_copy = dict(event_data)
    event_data_copy['object'] = dict(stripe_sub)
    event_data_copy['object']['status'] = 'canceled'
    handle_subscription_updated(event_data_copy)


# ---------------------------------------------------------------------------
# invoice.payment_succeeded
# ---------------------------------------------------------------------------

def handle_payment_succeeded(event_data):
    """Record successful payment. Subscription status is handled by subscription.updated."""
    from audit.services import log_event
    invoice = event_data['object']
    stripe_sub_id = invoice.get('subscription')
    amount = invoice.get('amount_paid', 0)
    logger.info(
        'Payment succeeded: subscription=%s amount=%s cents',
        stripe_sub_id, amount,
    )
    log_event(
        category='billing', action='payment_succeeded',
        detail={
            'stripe_subscription_id': stripe_sub_id,
            'amount_cents': amount,
            'currency': invoice.get('currency', 'usd'),
        },
    )


# ---------------------------------------------------------------------------
# invoice.payment_failed
# ---------------------------------------------------------------------------

def handle_payment_failed(event_data):
    """
    Handle failed payment. Stripe automatically sets the subscription
    to past_due, which we'll pick up via subscription.updated webhook.
    Log the failure for monitoring.
    """
    from audit.services import log_event
    invoice = event_data['object']
    stripe_sub_id = invoice.get('subscription')
    customer_id = invoice.get('customer')
    amount = invoice.get('amount_due', 0)

    logger.warning(
        'Payment failed: subscription=%s customer=%s amount=%s cents',
        stripe_sub_id, customer_id, amount,
    )
    log_event(
        category='billing', action='payment_failed', result='blocked',
        detail={
            'stripe_subscription_id': stripe_sub_id,
            'stripe_customer_id': customer_id,
            'amount_cents': amount,
            'currency': invoice.get('currency', 'usd'),
        },
    )

    # Send payment failure notification email
    try:
        from billing.email_utils import notify_payment_failed
        from billing.models import SchoolSubscription, Subscription
        school = None
        user = None
        if stripe_sub_id:
            try:
                school_sub = SchoolSubscription.objects.select_related('school__admin').get(
                    stripe_subscription_id=stripe_sub_id,
                )
                school = school_sub.school
            except SchoolSubscription.DoesNotExist:
                try:
                    ind_sub = Subscription.objects.select_related('user').get(
                        stripe_subscription_id=stripe_sub_id,
                    )
                    user = ind_sub.user
                except Subscription.DoesNotExist:
                    pass
        notify_payment_failed(school=school, user=user, detail={
            'amount_cents': amount,
            'currency': invoice.get('currency', 'usd'),
        })
    except Exception:
        logger.exception('Failed to send payment failure notification')
