"""
Stripe API service layer.

Encapsulates all Stripe API calls for subscriptions, customers,
checkout sessions, and billing portal.
"""
import logging

import stripe
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def _ensure_stripe_key():
    """Set Stripe API key lazily from settings (safe for tests and late config)."""
    if not stripe.api_key:
        stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def _find_existing_stripe_customer(email, metadata_key, metadata_value):
    """Return a Stripe customer we already made for this owner, or None.

    Asked before minting a new one, because the local row we would normally
    persist the id to does not always exist yet. A school student has no
    ``Subscription`` until checkout succeeds, so every failed attempt used to
    create a fresh Stripe customer and throw the id away — one student retrying
    a broken checkout eleven times left eleven customers behind.

    That is not just clutter. A customer is currency-locked once it has a
    subscription, so duplicates are how one person ends up with two currencies
    attached to their name and the next checkout dies on "You cannot combine
    currencies on a single customer".

    Matched on ``metadata`` among customers sharing the email, which is an
    immediately-consistent lookup — unlike ``Customer.search``, whose index lags
    by about a minute and would still duplicate on a fast retry. Oldest match
    wins so repeated attempts converge on one customer instead of walking
    forward through new ones.

    Never raises: if the lookup fails the caller creates a customer, which is
    exactly the old behaviour. A monitoring nicety must not block a payment.
    """
    if not email:
        return None
    try:
        found = stripe.Customer.list(email=email, limit=100)
    except Exception:  # noqa: BLE001 — fall back to creating, never block checkout
        logger.exception('Stripe customer lookup failed for %s', email)
        return None

    matches = [
        c for c in (found.get('data') or [])
        if str((c.get('metadata') or {}).get(metadata_key)) == str(metadata_value)
    ]
    if not matches:
        return None
    matches.sort(key=lambda c: c.get('created') or 0)
    if len(matches) > 1:
        logger.warning(
            'Stripe has %s customers for %s=%s (%s) — reusing the oldest, %s. '
            'Run "manage.py dedupe_stripe_customers" to clean up.',
            len(matches), metadata_key, metadata_value, email, matches[0]['id'],
        )
    return matches[0]['id']


def get_or_create_customer(user=None, school=None):
    """
    Get or create a Stripe Customer.
    For individual students: keyed on user.
    For institutes: keyed on school (via SchoolSubscription).
    """
    _ensure_stripe_key()
    if school:
        from billing.models import SchoolSubscription
        try:
            sub = school.subscription
        except SchoolSubscription.DoesNotExist:
            sub = None

        if sub and sub.stripe_customer_id:
            return sub.stripe_customer_id

        admin_email = school.admin.email if school.admin else ''
        customer_id = _find_existing_stripe_customer(
            admin_email, 'school_id', school.id)
        if customer_id is None:
            customer = stripe.Customer.create(
                email=admin_email,
                name=school.name,
                metadata={
                    'school_id': school.id,
                    'school_name': school.name,
                    'type': 'institute',
                },
            )
            customer_id = customer.id
        if sub:
            sub.stripe_customer_id = customer_id
            sub.save(update_fields=['stripe_customer_id'])
        return customer_id

    if user:
        from billing.models import Subscription
        try:
            sub = user.subscription
        except Subscription.DoesNotExist:
            sub = None

        if sub and sub.stripe_customer_id:
            return sub.stripe_customer_id

        # No local record of a customer — but there may still be one in Stripe
        # from an earlier attempt that had nowhere to persist the id.
        customer_id = _find_existing_stripe_customer(
            user.email, 'user_id', user.id)
        if customer_id is None:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.get_full_name() or user.username,
                metadata={
                    'user_id': user.id,
                    'username': user.username,
                    'type': 'individual',
                },
            )
            customer_id = customer.id
        if sub:
            sub.stripe_customer_id = customer_id
            sub.save(update_fields=['stripe_customer_id'])
        return customer_id

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
    _ensure_stripe_key()
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


def create_individual_checkout_session(user, package, request, stripe_coupon_id=None, trial_period_days=None):
    """
    Create a Stripe Checkout Session for an individual student subscription.
    Returns the Checkout Session object.

    If trial_period_days is set, Stripe collects card details but does not
    charge until the trial ends. After the trial, billing starts automatically.
    """
    _ensure_stripe_key()
    customer_id = get_or_create_customer(user=user)

    sub_data = {
        'metadata': {
            'user_id': user.id,
            'package_id': package.id,
            'type': 'individual',
        },
    }
    if trial_period_days:
        sub_data['trial_period_days'] = trial_period_days

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
        subscription_data=sub_data,
        billing_address_collection='required',
        payment_method_types=['card'],
    )

    if stripe_coupon_id:
        session_kwargs['discounts'] = [{'coupon': stripe_coupon_id}]

    session = stripe.checkout.Session.create(**session_kwargs)
    return session


def create_pending_registration_checkout_session(email, package, request, stripe_coupon_id=None):
    """
    Create a Stripe Checkout Session for a new individual student who has not
    yet had an account created.  The account is created after payment succeeds
    (via the success redirect or webhook).
    """
    _ensure_stripe_key()

    session_kwargs = dict(
        customer_email=email,
        mode='subscription',
        line_items=[{'price': package.stripe_price_id, 'quantity': 1}],
        success_url=request.build_absolute_uri(
            reverse('billing_success')
        ) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri(
            reverse('register_individual_student')
        ),
        metadata={
            'type': 'pending_individual_registration',
            'package_id': package.id,
        },
        subscription_data={
            'metadata': {
                'type': 'pending_individual_registration',
                'package_id': package.id,
            },
        },
        billing_address_collection='required',
        payment_method_types=['card'],
    )
    if stripe_coupon_id:
        session_kwargs['discounts'] = [{'coupon': stripe_coupon_id}]

    return stripe.checkout.Session.create(**session_kwargs)


def create_pending_institute_checkout_session(email, plan, request,
                                             trial_period_days=14,
                                             stripe_coupon_id=None):
    """Checkout for an institute whose account does not exist yet.

    The card is collected now; Stripe charges nothing until the trial ends, and
    a subscription cancelled inside the trial is never invoiced. So this asks
    for a card up front without asking for money up front — which is the whole
    point of gating account creation on it.

    ``payment_method_collection='always'`` is set explicitly rather than left to
    Stripe's default: the default for a trialling subscription has moved before,
    and an account created without a card on file is exactly the bug this
    replaces.
    """
    _ensure_stripe_key()

    sub_metadata = {
        'type': 'pending_institute_registration',
        'plan_id': plan.id,
    }
    session_kwargs = dict(
        customer_email=email,
        mode='subscription',
        line_items=[{'price': plan.stripe_price_id, 'quantity': 1}],
        success_url=request.build_absolute_uri(
            reverse('institute_checkout_success')
        ) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri(
            reverse('register_teacher_center')
        ),
        metadata=dict(sub_metadata),
        subscription_data={
            'metadata': dict(sub_metadata),
            'trial_period_days': trial_period_days,
        },
        billing_address_collection='required',
        payment_method_types=['card'],
        payment_method_collection='always',
    )
    if stripe_coupon_id:
        session_kwargs['discounts'] = [{'coupon': stripe_coupon_id}]

    return stripe.checkout.Session.create(**session_kwargs)


def create_student_checkout_session(user, package, request, stripe_coupon_id=None):
    """
    Create a Stripe Checkout Session for a school student subscription.
    School students are invited by HoI and need their own $19.90/mo subscription.
    """
    _ensure_stripe_key()
    customer_id = get_or_create_customer(user=user)

    session_kwargs = dict(
        customer=customer_id,
        mode='subscription',
        line_items=[{'price': package.stripe_price_id, 'quantity': 1}],
        success_url=request.build_absolute_uri(
            reverse('complete_profile_payment_success')
        ),
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
    _ensure_stripe_key()
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
    """Add a module as a subscription item, billed at its own price."""
    _ensure_stripe_key()
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
    _ensure_stripe_key()
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
    _ensure_stripe_key()
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
    _ensure_stripe_key()
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
    _ensure_stripe_key()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session


# ---------------------------------------------------------------------------
# Admin Sync Helpers
# ---------------------------------------------------------------------------

def _stripe_configured():
    """Return True if STRIPE_SECRET_KEY is set and non-empty."""
    return bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))


def sync_plan_to_stripe(plan):
    """
    Create or update a Stripe Product + Price for an InstitutePlan.
    Returns the new stripe_price_id.
    """
    _ensure_stripe_key()
    if not _stripe_configured():
        raise ValueError('Stripe is not configured.')

    product_id = f'institute_plan_{plan.slug}'

    # Create or update product
    try:
        product = stripe.Product.retrieve(product_id)
        stripe.Product.modify(product_id, name=plan.name, active=plan.is_active)
    except stripe.error.InvalidRequestError:  # Product does not exist — create it
        product = stripe.Product.create(
            id=product_id,
            name=plan.name,
            active=plan.is_active,
            metadata={'plan_id': plan.id, 'type': 'institute_plan'},
        )

    # Always create a new price (Stripe prices are immutable)
    price = stripe.Price.create(
        product=product.id,
        unit_amount=int(plan.price * 100),
        currency=settings.STRIPE_CURRENCY,
        recurring={'interval': 'month'},
    )

    # Archive old price if different
    if plan.stripe_price_id and plan.stripe_price_id != price.id:
        try:
            stripe.Price.modify(plan.stripe_price_id, active=False)
        except stripe.error.StripeError as e:
            logger.warning('Stripe cleanup failed: %s', e)

    plan.stripe_price_id = price.id
    plan.save(update_fields=['stripe_price_id'])
    return price.id


def _module_stripe_product(module_product):
    """The Stripe Product this module already lives on, or a new one.

    Looked up in the order that finds an EXISTING product first, because
    creating a second one for a module that already has one is how the Stripe
    catalogue ends up with two "Teachers Attendance" entries and a sync command
    that cannot tell which is real:

    1. The product behind the price the row currently names. This is the
       authoritative answer whenever the module has ever been priced, and the
       one ``reprice_module`` uses.
    2. The deterministic id this function used to assume, ``module_<slug>``,
       which is right only for products this function created.
    3. Create one — stamped with ``module_slug``, the key
       ``sync_stripe_prices`` matches on. The old metadata used ``module``,
       which that matcher does not read, so products made here were invisible
       to it and fell through to a six-name keyword fallback.
    """
    if module_product.stripe_price_id:
        try:
            existing = stripe.Price.retrieve(module_product.stripe_price_id)
            product_id = (existing.product if isinstance(existing.product, str)
                          else existing.product.id)
            return stripe.Product.modify(
                product_id,
                name=module_product.name,
                active=module_product.is_active,
            )
        except stripe.error.StripeError as e:
            logger.warning(
                'Could not reach the product behind price %s for module %s '
                '(%s) — falling back to a lookup by id.',
                module_product.stripe_price_id, module_product.module, e,
            )

    legacy_id = f'module_{module_product.module}'
    try:
        stripe.Product.retrieve(legacy_id)
        return stripe.Product.modify(
            legacy_id,
            name=module_product.name,
            active=module_product.is_active,
        )
    except stripe.error.InvalidRequestError:
        pass

    return stripe.Product.create(
        id=legacy_id,
        name=module_product.name,
        active=module_product.is_active,
        metadata={
            'module': module_product.module,
            'module_slug': module_product.module,
            'type': 'module',
        },
    )


def sync_module_to_stripe(module_product):
    """Point a ModuleProduct at a Stripe Price for its current amount.

    Backs the super-admin "Sync to Stripe" button, so it is the one repricing
    path a human can reach without a shell — and it must therefore behave the
    same as ``manage.py reprice_module``: a new Price on the module's EXISTING
    product, the row repointed, the superseded price archived.

    Returns the new stripe_price_id.

    Note what it does not do, and cannot: schools already subscribed keep the
    price their subscription item names. This changes what NEW subscribers pay.
    Moving existing schools is a price rise for a paying customer and lives
    behind ``reprice_module --migrate-existing``, which lists them first.
    """
    _ensure_stripe_key()
    if not _stripe_configured():
        raise ValueError('Stripe is not configured.')

    product = _module_stripe_product(module_product)

    price = stripe.Price.create(
        product=product.id,
        unit_amount=int(module_product.price * 100),
        currency=settings.STRIPE_CURRENCY,
        recurring={'interval': 'month'},
        metadata={'module_slug': module_product.module},
    )

    # Archive the superseded price. Both prices sit on the same product and so
    # answer to the same module_slug, and sync_stripe_prices only considers
    # active prices — leaving the old one active gives the next sync two
    # candidates for one module and a chance to repoint this row back to the
    # amount it was just moved off. Archiving never stops an existing
    # subscription item billing; it only prevents new use.
    old_price_id = module_product.stripe_price_id
    if old_price_id and old_price_id != price.id:
        try:
            stripe.Price.modify(old_price_id, active=False)
        except stripe.error.StripeError as e:
            logger.warning(
                'Repriced module %s to %s but could not archive the old price '
                '%s: %s. While it is active, sync_stripe_prices may repoint '
                'this module back to it.',
                module_product.module, price.id, old_price_id, e,
            )

    module_product.stripe_price_id = price.id
    module_product.save(update_fields=['stripe_price_id'])
    return price.id


# ---------------------------------------------------------------------------
# AI Question Import — half price for the first year
# ---------------------------------------------------------------------------
#
# The offer the plans page advertises, applied automatically. There is no code
# for anyone to type: adding an AI import module attaches the coupon, and
# Stripe drops it by itself once the twelve months are up.
#
# The coupon is scoped with ``applies_to.products`` so it discounts ONLY the AI
# import line. A subscription-level coupon with no scope would take 50% off the
# institute's own plan too, which is not the offer and is not recoverable once
# invoiced.


def ai_intro_coupon_id():
    """A stable id that changes when the terms do.

    Baking the terms into the id means a coupon can never be reused at terms it
    was not created with: change the percentage or the length and the next call
    creates a new coupon rather than quietly attaching the old one.
    """
    from billing import ai_tiers

    return (f'ai-import-intro-{ai_tiers.INTRO_DISCOUNT_PERCENT}off-'
            f'{ai_tiers.INTRO_DISCOUNT_MONTHS}m')


def _ai_intro_products():
    """Stripe product ids for the AI import tiers.

    ``sync_module_to_stripe`` creates products at a deterministic id, so these
    are derivable without a round trip.
    """
    from billing.models import ModuleProduct
    from billing import ai_tiers

    return [
        f'module_{slug}' for slug in ModuleProduct.objects
        .filter(module__startswith=ai_tiers.MODULE_PREFIX)
        .values_list('module', flat=True)
    ]


def ensure_ai_intro_coupon():
    """The intro coupon, created once and reused. Returns its id, or None."""
    from billing import ai_tiers

    _ensure_stripe_key()
    coupon_id = ai_intro_coupon_id()
    try:
        stripe.Coupon.retrieve(coupon_id)
        return coupon_id
    except stripe.error.InvalidRequestError:
        pass  # Not there yet — create it below.

    products = _ai_intro_products()
    if not products:
        logger.error('No AI import products in the catalogue — cannot scope the '
                     'intro coupon, and an unscoped one would discount the '
                     "institute's whole plan. Not creating it.")
        return None

    coupon = stripe.Coupon.create(
        id=coupon_id,
        percent_off=float(ai_tiers.INTRO_DISCOUNT_PERCENT),
        duration='repeating',
        duration_in_months=ai_tiers.INTRO_DISCOUNT_MONTHS,
        name=(f'AI Question Import — {ai_tiers.INTRO_DISCOUNT_PERCENT}% off '
              f'the {ai_tiers.INTRO_DISCOUNT_LABEL}'),
        applies_to={'products': products},
        metadata={'type': 'ai_import_intro'},
    )
    return coupon.id


def apply_ai_intro_discount(school_subscription):
    """Put the school's AI import module on its first-year price.

    Returns ``(applied, error)``. ``error`` is written for the person who just
    clicked Activate, and every caller must show it: the plans page promised
    half price, so a school that ends up without the discount is being charged
    twice what it was quoted. Silence here is how that goes unnoticed.

    Never overwrites a discount the subscription already has. Institutes can
    register with their own discount code, and a coupon set on the subscription
    replaces whatever was there — trading their negotiated discount for this
    one, with no record of what was lost.
    """
    if not school_subscription.stripe_subscription_id:
        # Trial or locally-activated module: nothing is being charged, so
        # there is nothing to discount.
        return False, None

    _ensure_stripe_key()
    coupon_id = ai_intro_coupon_id()

    try:
        subscription = stripe.Subscription.retrieve(
            school_subscription.stripe_subscription_id,
        )
    except stripe.error.StripeError as e:
        logger.exception('Could not read subscription %s to apply the AI intro '
                         'discount', school_subscription.stripe_subscription_id)
        return False, str(e)

    existing = getattr(subscription, 'discount', None)
    existing_coupon = getattr(existing, 'coupon', None) if existing else None
    existing_id = getattr(existing_coupon, 'id', None)

    if existing_id == coupon_id:
        # Already on it — including after a tier switch, which keeps the
        # original twelve-month clock rather than restarting it.
        return True, None

    if existing_id:
        logger.warning(
            'Subscription %s already carries coupon %s — not replacing it with '
            'the AI intro discount.',
            school_subscription.stripe_subscription_id, existing_id,
        )
        return False, (
            'Your subscription already has a discount applied, so the AI '
            'import introductory price was not added on top of it. Contact '
            'support to have it applied.'
        )

    try:
        coupon_id = ensure_ai_intro_coupon()
        if not coupon_id:
            return False, ('The introductory discount is not set up in Stripe '
                           'yet. Contact support before you are invoiced.')
        stripe.Subscription.modify(
            school_subscription.stripe_subscription_id, coupon=coupon_id,
        )
    except stripe.error.StripeError as e:
        logger.exception('Failed to apply the AI intro discount to %s',
                         school_subscription.stripe_subscription_id)
        return False, str(e)

    return True, None


def _build_stripe_coupon_kwargs(code_obj):
    """Build kwargs for stripe.Coupon.create from any discount/coupon model instance."""
    kwargs = {
        'percent_off': float(code_obj.discount_percent),
        'duration': getattr(code_obj, 'duration', 'forever') or 'forever',
        'name': f'{code_obj.code} ({code_obj.discount_percent}% off)',
        'metadata': {'code': code_obj.code},
    }
    if kwargs['duration'] == 'repeating' and getattr(code_obj, 'duration_in_months', None):
        kwargs['duration_in_months'] = code_obj.duration_in_months
    return kwargs


def ensure_stripe_coupon(code_obj):
    """Give a partial discount code the Stripe coupon its checkout needs.

    Returns ``(synced, error)``. Never raises — the caller decides how loudly
    to fail, and every caller must say something: a partial code with no
    coupon id is silently ignored by Stripe Checkout, so the student pays the
    FULL price while the subscription records the discount they were promised.
    Reporting "created" for a code in that state is how an overcharge gets set
    up months before anyone redeems it.

    A 100%-off code needs no coupon — it never reaches Stripe at all — so it is
    reported as synced. Works for both ``DiscountCode`` and
    ``InstituteDiscountCode``; the fields it reads are common to both.
    """
    if getattr(code_obj, 'is_fully_free', False):
        return True, None
    if code_obj.stripe_coupon_id:
        return True, None
    if not _stripe_configured():
        return False, 'Stripe is not configured on this server (no STRIPE_SECRET_KEY).'
    try:
        _ensure_stripe_key()
        kwargs = _build_stripe_coupon_kwargs(code_obj)
        kwargs['metadata']['discount_code_id'] = code_obj.id
        coupon = stripe.Coupon.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — reported to the caller, not swallowed
        logger.exception(
            'Stripe coupon creation failed for code %s (%s%% off)',
            getattr(code_obj, 'code', code_obj),
            getattr(code_obj, 'discount_percent', '?'),
        )
        return False, str(e)

    code_obj.stripe_coupon_id = coupon.id
    code_obj.save(update_fields=['stripe_coupon_id'])
    return True, None


#: What to tell an admin whose code was saved without a working coupon.
UNSYNCED_COUPON_WARNING = (
    'Discount code "{code}" was saved, but its Stripe coupon could NOT be '
    'created ({error}). Students cannot check out with this code until it is '
    'synced — they would otherwise be charged the full price. Re-save the code '
    'once Stripe is reachable, or run "manage.py sync_stripe_coupons".'
)


def sync_discount_to_stripe(discount_code):
    """
    Create a Stripe Coupon for an InstituteDiscountCode.
    Skips if discount is 100% (fully free). Returns coupon_id.
    """
    _ensure_stripe_key()
    if not _stripe_configured():
        raise ValueError('Stripe is not configured.')

    if discount_code.is_fully_free:
        return ''

    kwargs = _build_stripe_coupon_kwargs(discount_code)
    kwargs['metadata']['discount_code_id'] = discount_code.id
    coupon = stripe.Coupon.create(**kwargs)

    discount_code.stripe_coupon_id = coupon.id
    discount_code.save(update_fields=['stripe_coupon_id'])
    return coupon.id


def sync_individual_discount_to_stripe(discount_code):
    """
    Create a Stripe Coupon for a DiscountCode (individual student).
    Skips if discount is 100% (fully free). Returns coupon_id.
    """
    _ensure_stripe_key()
    if not _stripe_configured():
        raise ValueError('Stripe is not configured.')

    if discount_code.is_fully_free:
        return ''

    kwargs = _build_stripe_coupon_kwargs(discount_code)
    kwargs['metadata']['discount_code_id'] = discount_code.id
    coupon = stripe.Coupon.create(**kwargs)

    discount_code.stripe_coupon_id = coupon.id
    discount_code.save(update_fields=['stripe_coupon_id'])
    return coupon.id


# ---------------------------------------------------------------------------
# Parent Invoice Payment
# ---------------------------------------------------------------------------

def calculate_stripe_fee(amount):
    """
    Calculate Stripe processing fee for a given amount.
    Standard rate: 2.9% + $0.30 NZD.
    Returns (fee, total_charged) both as Decimal.
    """
    from decimal import Decimal, ROUND_HALF_UP
    amount = Decimal(str(amount))
    fee = (amount * Decimal('0.029') + Decimal('0.30')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total_charged = amount + fee
    return fee, total_charged


def create_invoice_checkout_session(parent, amount_applied, invoice_allocations, request, currency=None):
    """
    Create a Stripe Checkout Session for a parent paying outstanding invoice balances.

    amount_applied  -- amount that will be applied to invoices (excluding Stripe fee), Decimal
    invoice_allocations -- list of dicts: [{"invoice_id": 1, "amount": "120.00"}, ...]
    Returns (InvoiceStripePayment, stripe.Session).
    """
    from decimal import Decimal
    from billing.models import InvoiceStripePayment

    _ensure_stripe_key()

    amount_applied = Decimal(str(amount_applied))
    fee, total_charged = calculate_stripe_fee(amount_applied)
    total_cents = int((total_charged * 100).to_integral_value())

    if not currency:
        raise ValueError(
            'currency is required for invoice checkout sessions — '
            'pass the school\'s default_currency, not the .env STRIPE_CURRENCY.'
        )
    used_currency = currency.lower()

    invoice_ids = [str(a['invoice_id']) for a in invoice_allocations]
    description = 'Invoice payment - {} invoice(s): {}'.format(len(invoice_ids), ', '.join(invoice_ids))

    # Create pending record before hitting Stripe so we have a pk for metadata
    isp = InvoiceStripePayment.objects.create(
        parent=parent,
        total_charged=total_charged,
        amount_applied=amount_applied,
        stripe_fee=fee,
        currency=used_currency,
        invoice_allocations=invoice_allocations,
        status=InvoiceStripePayment.STATUS_PENDING,
    )

    success_url = request.build_absolute_uri(
        reverse('parent_invoice_pay_success')
    ) + '?isp_id={}'.format(isp.pk)
    cancel_url = request.build_absolute_uri(reverse('parent_invoices'))

    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=[{
            'price_data': {
                'currency': used_currency,
                'unit_amount': total_cents,
                'product_data': {
                    'name': 'Invoice Payment',
                    'description': description,
                },
            },
            'quantity': 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            'type': 'invoice_payment',
            'isp_id': str(isp.pk),
            'parent_id': str(parent.pk),
            'amount_applied': str(amount_applied),
            'invoice_ids': ','.join(invoice_ids),
        },
        payment_method_types=['card'],
        billing_address_collection='auto',
    )

    isp.stripe_checkout_session_id = session.id
    isp.save(update_fields=['stripe_checkout_session_id'])

    return isp, session
