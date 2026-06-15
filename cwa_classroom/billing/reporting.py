"""
Earnings reporting from Stripe (source of truth for actual revenue).

The super-admin Subscriptions Overview shows actual paid revenue for the
current and previous month, split into student (individual / B2C) vs
institute (school) subscriptions.

"Actual" = the sum of paid Stripe invoices in the period — real cash,
post-discount and post-refund. 100%-discount subscriptions never reach
Stripe, so they correctly contribute $0.

If Stripe is unconfigured or the API errors, callers fall back to a local
(discount-aware) estimate and flag the figures as estimates.
"""
import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes — avoid hitting Stripe on every page load
_CENTS = Decimal('100')


class StripeUnavailable(Exception):
    """Raised when Stripe cannot be reached / is not configured."""


def _customer_id_sets():
    """Return (student_customer_ids, institute_customer_ids) from local data.

    Paid invoices are attributed to a panel by matching invoice.customer
    against these sets.
    """
    from billing.models import Subscription, SchoolSubscription
    students = set(
        Subscription.objects.exclude(stripe_customer_id='')
        .values_list('stripe_customer_id', flat=True),
    )
    institutes = set(
        SchoolSubscription.objects.exclude(stripe_customer_id='')
        .values_list('stripe_customer_id', flat=True),
    )
    return students, institutes


def get_paid_revenue(period_start, period_end):
    """Sum paid Stripe invoices in [period_start, period_end) per panel.

    period_start / period_end are timezone-aware datetimes. Returns
    {'student': Decimal, 'institute': Decimal}. Raises StripeUnavailable
    if Stripe is not configured or the API call fails.
    """
    if not getattr(settings, 'STRIPE_SECRET_KEY', ''):
        raise StripeUnavailable('STRIPE_SECRET_KEY not set')

    cache_key = (
        f'earnings:paid:{int(period_start.timestamp())}'
        f':{int(period_end.timestamp())}'
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not stripe.api_key:
        stripe.api_key = settings.STRIPE_SECRET_KEY

    students, institutes = _customer_id_sets()
    totals = {'student': Decimal('0.00'), 'institute': Decimal('0.00')}

    try:
        invoices = stripe.Invoice.list(
            status='paid',
            created={
                'gte': int(period_start.timestamp()),
                'lt': int(period_end.timestamp()),
            },
            limit=100,
        )
        for inv in invoices.auto_paging_iter():
            amount = (Decimal(inv.get('amount_paid', 0)) / _CENTS)
            if amount <= 0:
                continue
            customer = inv.get('customer')
            if customer in students:
                totals['student'] += amount
            elif customer in institutes:
                totals['institute'] += amount
            # invoices for unknown customers are ignored (not our subs)
    except stripe.error.StripeError as exc:  # noqa: F841
        logger.warning('Stripe earnings fetch failed: %s', exc)
        raise StripeUnavailable(str(exc))
    except Exception as exc:  # network etc.
        logger.warning('Stripe earnings fetch error: %s', exc)
        raise StripeUnavailable(str(exc))

    cache.set(cache_key, totals, CACHE_TTL)
    return totals
