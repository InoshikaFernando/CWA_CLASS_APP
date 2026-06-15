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


# Subscriptions are tagged with metadata.type at creation (see stripe_service).
STUDENT_TYPES = {'individual', 'school_student'}
INSTITUTE_TYPES = {'institute'}


def get_subscription_counts():
    """Count live Stripe subscriptions per panel, by status — Stripe is the
    source of truth for "how many paying students / institutes".

    "Students" = individual + school_student (every paying student, however
    enrolled). "Institutes" = institute-type subscriptions. Module/overage
    items live inside an institute subscription and are not counted separately.

    Returns {
      'student':   {'paid': int, 'trial': int, 'other': int, 'total': int},
      'institute': {'paid': int, 'trial': int, 'other': int, 'total': int},
    }  where paid = status 'active', trial = 'trialing', other = the rest
    (past_due / canceled / unpaid / paused …).

    Raises StripeUnavailable if Stripe is not configured or the API fails.
    """
    if not getattr(settings, 'STRIPE_SECRET_KEY', ''):
        raise StripeUnavailable('STRIPE_SECRET_KEY not set')

    cached = cache.get('subs:counts')
    if cached is not None:
        return cached

    if not stripe.api_key:
        stripe.api_key = settings.STRIPE_SECRET_KEY

    counts = {
        'student': {'paid': 0, 'trial': 0, 'other': 0, 'total': 0},
        'institute': {'paid': 0, 'trial': 0, 'other': 0, 'total': 0},
    }
    try:
        subs = stripe.Subscription.list(status='all', limit=100)
        for s in subs.auto_paging_iter():
            md = s.get('metadata') or {}
            sub_type = md.get('type')
            if sub_type in STUDENT_TYPES:
                panel = 'student'
            elif sub_type in INSTITUTE_TYPES:
                panel = 'institute'
            else:
                continue
            status = s.get('status')
            if status == 'active':
                counts[panel]['paid'] += 1
            elif status == 'trialing':
                counts[panel]['trial'] += 1
            else:
                counts[panel]['other'] += 1
            counts[panel]['total'] += 1
    except stripe.error.StripeError as exc:  # noqa: F841
        logger.warning('Stripe subscription count failed: %s', exc)
        raise StripeUnavailable(str(exc))
    except Exception as exc:
        logger.warning('Stripe subscription count error: %s', exc)
        raise StripeUnavailable(str(exc))

    cache.set('subs:counts', counts, CACHE_TTL)
    return counts


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
    """Sum paid SUBSCRIPTION Stripe invoices in [period_start, period_end).

    period_start / period_end are timezone-aware datetimes.

    Only invoices with a subscription billing_reason are counted (recurring
    revenue), so one-off / manual invoices don't inflate the figure. Amounts
    are tracked per currency; mixed currencies are flagged rather than summed
    blindly.

    Returns:
        {
          'student': Decimal, 'institute': Decimal,   # summed amount_paid
          'student_count': int, 'institute_count': int,
          'currency': 'NZD' | 'MIXED' | '',           # currency seen
        }
    Raises StripeUnavailable if Stripe is not configured or the API fails.
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
    counts = {'student': 0, 'institute': 0}
    currencies = set()

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
            # Only recurring subscription invoices count as MRR revenue.
            if not (inv.get('billing_reason') or '').startswith('subscription'):
                continue
            amount = (Decimal(inv.get('amount_paid', 0)) / _CENTS)
            if amount <= 0:
                continue
            customer = inv.get('customer')
            if customer in students:
                panel = 'student'
            elif customer in institutes:
                panel = 'institute'
            else:
                continue  # not one of our subscriptions
            totals[panel] += amount
            counts[panel] += 1
            currencies.add((inv.get('currency') or '').upper())
    except stripe.error.StripeError as exc:  # noqa: F841
        logger.warning('Stripe earnings fetch failed: %s', exc)
        raise StripeUnavailable(str(exc))
    except Exception as exc:  # network etc.
        logger.warning('Stripe earnings fetch error: %s', exc)
        raise StripeUnavailable(str(exc))

    if len(currencies) > 1:
        logger.warning('Mixed currencies in paid invoices: %s', currencies)

    result = {
        'student': totals['student'],
        'institute': totals['institute'],
        'student_count': counts['student'],
        'institute_count': counts['institute'],
        'currency': (
            next(iter(currencies)) if len(currencies) == 1
            else ('MIXED' if currencies else '')
        ),
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result
