"""
Stripe API service layer.

Encapsulates all Stripe API calls for subscriptions, customers,
checkout sessions, and billing portal.
"""
import logging

import stripe
from django.conf import settings
from django.urls import reverse

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def get_or_create_customer(user=None, school=None):
    """
    Get or create a Stripe Customer.
    For individual students: keyed on user.
    For institutes: keyed on school (via SchoolSubscription).
    """
    if school:
        from billing.models import SchoolSubscription
        try:
            sub = school.subscription
        except SchoolSubscription.DoesNotExist:
            sub = None

        if sub and sub.stripe_customer_id:
            return sub.stripe_customer_id

        customer = stripe.Customer.create(
            email=school.admin.email if school.admin else '',
            name=school.name,
            metadata={
                'school_id': school.id,
                'school_name': school.name,
                'type': 'institute',
            },
        )
        if sub:
            sub.stripe_customer_id = customer.id
            sub.save(update_fields=['stripe_customer_id'])
        return customer.id

    if user:
        from billing.models import Subscription
        try:
            sub = user.subscription
        except Subscription.DoesNotExist:
            sub = None

        if sub and sub.stripe_customer_id:
            return sub.stripe_customer_id

        customer = stripe.Customer.create(
            email=user.email,
            name=user.get_full_name() or user.username,
            metadata={
                'user_id': user.id,
                'username': user.username,
                'type': 'individual',
            },
        )
        if sub:
            sub.stripe_customer_id = customer.id
            sub.save(update_fields=['stripe_customer_id'])
        return customer.id

    raise ValueError('Must provide either user or school')


# ---------------------------------------------------------------------------
# Checkout Sessions
# ---------------------------------------------------------------------------

def create_institute_checkout_session(school, plan, request, trial_period_days=None, stripe_coupon_id=None):
    """
    Create a Stripe Checkout Session for an institute subscription.
    Returns the Checkout Session object (use session.url to redirect).

    If trial_period_days is set, Stripe collects card details but does not
    charge until the trial ends. After the trial, billing starts automatically.
    If stripe_coupon_id is set, applies the discount coupon to the subscription.
    """
    customer_id = get_or_create_customer(school=school)

    line_items = [{'price': plan.stripe_price_id, 'quantity': 1}]

    sub_data = {
        'metadata': {
            'school_id': school.id,
            'plan_id': plan.id,
            'type': 'institute',
        },
    }
    if trial_period_days:
        sub_data['trial_period_days'] = trial_period_days

    session_kwargs = dict(
        customer=customer_id,
        mode='subscription',
        line_items=line_items,
        success_url=request.build_absolute_uri(
            reverse('institute_checkout_success')
        ) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri(
            reverse('institute_plan_select')
        ),
        metadata={
            'school_id': school.id,
            'plan_id': plan.id,
            'type': 'institute',
        },
        subscription_data=sub_data,
        billing_address_collection='required',
        payment_method_types=['card'],
    )

    if stripe_coupon_id:
        session_kwargs['discounts'] = [{'coupon': stripe_coupon_id}]

    session = stripe.checkout.Session.create(**session_kwargs)
    return session


def create_individual_checkout_session(user, package, request, stripe_coupon_id=None):
    """
    Create a Stripe Checkout Session for an individual student subscription.
    Returns the Checkout Session object.
    """
    customer_id = get_or_create_customer(user=user)

    session_kwargs = dict(
        customer=customer_id,
        mode='subscription',
        line_items=[{'price': package.stripe_price_id, 'quantity': 1}],
        success_url=request.build_absolute_uri(
            reverse('billing_success')
        ) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri(
            reverse('billing_cancel')
        ),
        metadata={
            'user_id': user.id,
            'package_id': package.id,
            'type': 'individual',
        },
        subscription_data={
            'metadata': {
                'user_id': user.id,
                'package_id': package.id,
                'type': 'individual',
            },
        },
        billing_address_collection='required',
        payment_method_types=['card'],
    )

    if stripe_coupon_id:
        session_kwargs['discounts'] = [{'coupon': stripe_coupon_id}]

    session = stripe.checkout.Session.create(**session_kwargs)
    return session


def create_student_checkout_session(user, package, request, stripe_coupon_id=None):
    """
    Create a Stripe Checkout Session for a school student subscription.
    School students are invited by HoI and need their own $19.90/mo subscription.
    """
    customer_id = get_or_create_customer(user=user)

    session_kwargs = dict(
        customer=customer_id,
        mode='subscription',
        line_items=[{'price': package.stripe_price_id, 'quantity': 1}],
        success_url=request.build_absolute_uri(
            reverse('subjects_hub')
        ) + '?subscription=active',
        cancel_url=request.build_absolute_uri(
            reverse('complete_profile')
        ),
        metadata={
            'user_id': user.id,
            'package_id': package.id,
            'type': 'school_student',
        },
        subscription_data={
            'metadata': {
                'user_id': user.id,
                'package_id': package.id,
                'type': 'school_student',
            },
        },
        billing_address_collection='required',
        payment_method_types=['card'],
    )

    if stripe_coupon_id:
        session_kwargs['discounts'] = [{'coupon': stripe_coupon_id}]

    session = stripe.checkout.Session.create(**session_kwargs)
    return session


# ---------------------------------------------------------------------------
# Plan Changes
# ---------------------------------------------------------------------------

def change_institute_plan(school_subscription, new_plan):
    """
    Change an institute's subscription to a different plan.
    Prorates the change.
    """
    if not school_subscription.stripe_subscription_id:
        raise ValueError('No active Stripe subscription to modify')

    stripe_sub = stripe.Subscription.retrieve(
        school_subscription.stripe_subscription_id
    )

    # Find the plan item (not module items)
    plan_item = None
    for item in stripe_sub['items']['data']:
        if item['metadata'].get('type') != 'module':
            plan_item = item
            break

    if not plan_item:
        raise ValueError('Cannot find plan item on Stripe subscription')

    stripe.Subscription.modify(
        school_subscription.stripe_subscription_id,
        items=[{
            'id': plan_item.id,
            'price': new_plan.stripe_price_id,
        }],
        proration_behavior='create_prorations',
        metadata={
            'school_id': school_subscription.school_id,
            'plan_id': new_plan.id,
            'type': 'institute',
        },
    )

    school_subscription.plan = new_plan
    school_subscription.save(update_fields=['plan', 'updated_at'])
    return True


# ---------------------------------------------------------------------------
# Module Add-ons
# ---------------------------------------------------------------------------

def add_module_to_subscription(school_subscription, module_slug, stripe_price_id):
    """Add a module as a subscription item ($10/mo add-on)."""
    if not school_subscription.stripe_subscription_id:
        raise ValueError('No active Stripe subscription')

    item = stripe.SubscriptionItem.create(
        subscription=school_subscription.stripe_subscription_id,
        price=stripe_price_id,
        quantity=1,
        metadata={
            'type': 'module',
            'module': module_slug,
            'school_id': school_subscription.school_id,
        },
    )

    from billing.models import ModuleSubscription
    ModuleSubscription.objects.update_or_create(
        school_subscription=school_subscription,
        module=module_slug,
        defaults={
            'stripe_subscription_item_id': item.id,
            'is_active': True,
            'deactivated_at': None,
        },
    )
    return item


def remove_module_from_subscription(school_subscription, module_slug):
    """Remove a module subscription item."""
    from billing.models import ModuleSubscription
    from django.utils import timezone

    try:
        mod_sub = ModuleSubscription.objects.get(
            school_subscription=school_subscription,
            module=module_slug,
            is_active=True,
        )
    except ModuleSubscription.DoesNotExist:
        return False

    if mod_sub.stripe_subscription_item_id:
        stripe.SubscriptionItem.delete(
            mod_sub.stripe_subscription_item_id,
            proration_behavior='create_prorations',
        )

    mod_sub.is_active = False
    mod_sub.deactivated_at = timezone.now()
    mod_sub.save(update_fields=['is_active', 'deactivated_at'])
    return True


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def cancel_subscription(stripe_subscription_id, at_period_end=True):
    """Cancel a subscription, optionally at end of current period."""
    if at_period_end:
        stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=True,
        )
    else:
        stripe.Subscription.cancel(stripe_subscription_id)


# ---------------------------------------------------------------------------
# Usage Reporting (Invoice Overages)
# ---------------------------------------------------------------------------

def report_invoice_overage(school_subscription, overage_count):
    """Report usage-based metered billing for extra invoices."""
    if not school_subscription.plan or not school_subscription.plan.stripe_overage_price_id:
        logger.warning(
            'No overage price configured for plan %s',
            school_subscription.plan,
        )
        return

    # Find the metered subscription item
    if not school_subscription.stripe_subscription_id:
        return

    stripe_sub = stripe.Subscription.retrieve(
        school_subscription.stripe_subscription_id
    )

    overage_item = None
    for item in stripe_sub['items']['data']:
        if item['price']['id'] == school_subscription.plan.stripe_overage_price_id:
            overage_item = item
            break

    if not overage_item:
        # Add metered price as a subscription item
        overage_item = stripe.SubscriptionItem.create(
            subscription=school_subscription.stripe_subscription_id,
            price=school_subscription.plan.stripe_overage_price_id,
            metadata={'type': 'overage', 'school_id': school_subscription.school_id},
        )

    # Report usage
    stripe.SubscriptionItem.create_usage_record(
        overage_item.id,
        quantity=overage_count,
        action='increment',
    )


# ---------------------------------------------------------------------------
# Billing Portal
# ---------------------------------------------------------------------------

def create_billing_portal_session(customer_id, return_url):
    """Create a Stripe Billing Portal session for payment method management."""
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session
