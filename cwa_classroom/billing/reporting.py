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
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

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


# Allowed daily-graph windows (days). 5y = 1825.
DAILY_WINDOWS = [7, 30, 90, 365, 1825]


def _active_series_from_intervals(intervals, window_days):
    """Given [(panel, start_date, end_date_or_None)], build per-day active
    counts for the trailing `window_days` ending today (inclusive).

    A subscription is "active" on day D if it started on/before D and had not
    ended on/before D. Uses a difference array + prefix sum (O(subs + days)).
    Returns {'labels': [...isodate], 'student': [...], 'institute': [...],
    'window_days': n}.
    """
    n = window_days
    today = timezone.localdate()
    start_day = today - timedelta(days=n - 1)
    end_excl = today + timedelta(days=1)
    diffs = {'student': [0] * (n + 1), 'institute': [0] * (n + 1)}

    for panel, start, end in intervals:
        if panel not in diffs or not start:
            continue
        lo = max(start, start_day)
        hi = min(end or end_excl, end_excl)
        if hi <= lo:
            continue
        i = max(0, (lo - start_day).days)
        j = min(n, (hi - start_day).days)
        if j <= i:
            continue
        diffs[panel][i] += 1
        diffs[panel][j] -= 1

    series = {}
    for panel in ('student', 'institute'):
        cur, vals = 0, []
        for k in range(n):
            cur += diffs[panel][k]
            vals.append(cur)
        series[panel] = vals
    labels = [(start_day + timedelta(days=k)).isoformat() for k in range(n)]
    return {
        'labels': labels,
        'student': series['student'],
        'institute': series['institute'],
        'window_days': n,
    }


def _ts_to_date(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(ts, dt_timezone.utc).date()


def get_daily_active_series(window_days):
    """Daily active-subscription counts (student vs institute) from Stripe.

    Reconstructs each subscription's live span from created → ended/canceled
    and counts how many were live on each day. Raises StripeUnavailable if
    Stripe is not configured or the API fails.
    """
    if window_days not in DAILY_WINDOWS:
        window_days = 30
    if not getattr(settings, 'STRIPE_SECRET_KEY', ''):
        raise StripeUnavailable('STRIPE_SECRET_KEY not set')

    cache_key = f'subs:daily_active:{window_days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    if not stripe.api_key:
        stripe.api_key = settings.STRIPE_SECRET_KEY

    intervals = []
    try:
        for s in stripe.Subscription.list(status='all', limit=100).auto_paging_iter():
            t = (s.get('metadata') or {}).get('type')
            if t in STUDENT_TYPES:
                panel = 'student'
            elif t in INSTITUTE_TYPES:
                panel = 'institute'
            else:
                continue
            start = _ts_to_date(s.get('created'))
            end = _ts_to_date(s.get('ended_at') or s.get('canceled_at'))
            intervals.append((panel, start, end))
    except stripe.error.StripeError as exc:  # noqa: F841
        logger.warning('Stripe daily-active fetch failed: %s', exc)
        raise StripeUnavailable(str(exc))
    except Exception as exc:
        logger.warning('Stripe daily-active fetch error: %s', exc)
        raise StripeUnavailable(str(exc))

    result = _active_series_from_intervals(intervals, window_days)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def get_daily_active_series_local(window_days):
    """Local-DB fallback for the daily active graph (used when Stripe is
    unavailable, e.g. local dev). Students from billing.Subscription,
    institutes from SchoolSubscription (no cancel timestamp → treated as
    live)."""
    if window_days not in DAILY_WINDOWS:
        window_days = 30
    from billing.models import Subscription, SchoolSubscription
    intervals = []
    for created, cancelled in Subscription.objects.values_list(
            'created_at', 'cancelled_at'):
        intervals.append((
            'student',
            timezone.localtime(created).date() if created else None,
            timezone.localtime(cancelled).date() if cancelled else None,
        ))
    for (created,) in SchoolSubscription.objects.values_list('created_at'):
        intervals.append((
            'institute',
            timezone.localtime(created).date() if created else None,
            None,
        ))
    return _active_series_from_intervals(intervals, window_days)


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
