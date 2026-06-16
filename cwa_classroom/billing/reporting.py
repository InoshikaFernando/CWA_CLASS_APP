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
      'student':   {'paid': int, 'trial': int, 'other': int, 'total': int,
                    'new_today': int, 'lost_today': int},
      'institute': {'paid': int, 'trial': int, 'other': int, 'total': int,
                    'new_today': int, 'lost_today': int},
    }  where paid = status 'active', trial = 'trialing', other = the rest
    (past_due / canceled / unpaid / paused …). new_today / lost_today count
    distinct entities whose subscription was created / ended today (local
    time), so they're consistent with the Stripe-sourced tiles above them.

    Raises StripeUnavailable if Stripe is not configured or the API fails.
    """
    if not getattr(settings, 'STRIPE_SECRET_KEY', ''):
        raise StripeUnavailable('STRIPE_SECRET_KEY not set')

    cached = cache.get('subs:counts')
    if cached is not None:
        return cached

    if not stripe.api_key:
        stripe.api_key = settings.STRIPE_SECRET_KEY

    today = timezone.localdate()

    # Track DISTINCT entities (schools / students), not subscription rows, so a
    # re-subscribe / duplicate test subscription doesn't inflate the count.
    sets = {
        p: {'paid': set(), 'trial': set(), 'other': set(), 'all': set(),
            'new_today': set(), 'lost_today': set()}
        for p in ('student', 'institute')
    }
    try:
        subs = stripe.Subscription.list(status='all', limit=100)
        for s in subs.auto_paging_iter():
            md = s.get('metadata') or {}
            sub_type = md.get('type')
            if sub_type in STUDENT_TYPES:
                panel = 'student'
                key = md.get('user_id') or s.get('id')
            elif sub_type in INSTITUTE_TYPES:
                panel = 'institute'
                key = md.get('school_id') or s.get('id')
            else:
                continue
            status = s.get('status')
            bucket = ('paid' if status == 'active'
                      else 'trial' if status == 'trialing' else 'other')
            sets[panel][bucket].add(key)
            sets[panel]['all'].add(key)
            if _ts_to_local_date(s.get('created')) == today:
                sets[panel]['new_today'].add(key)
            ended = _ts_to_local_date(s.get('ended_at') or s.get('canceled_at'))
            if ended == today:
                sets[panel]['lost_today'].add(key)
    except stripe.error.StripeError as exc:  # noqa: F841
        logger.warning('Stripe subscription count failed: %s', exc)
        raise StripeUnavailable(str(exc))
    except Exception as exc:
        logger.warning('Stripe subscription count error: %s', exc)
        raise StripeUnavailable(str(exc))

    counts = {
        p: {
            'paid': len(sets[p]['paid']),
            'trial': len(sets[p]['trial']),
            'other': len(sets[p]['other']),
            'total': len(sets[p]['all']),
            'new_today': len(sets[p]['new_today']),
            'lost_today': len(sets[p]['lost_today']),
        }
        for p in ('student', 'institute')
    }
    cache.set('subs:counts', counts, CACHE_TTL)
    return counts


# Allowed daily-graph windows (days). 5y = 1825.
DAILY_WINDOWS = [7, 30, 90, 365, 1825]


def _active_series_from_intervals(intervals, window_days):
    """Given [(panel, entity_key, start_date, end_date_or_None)], build per-day
    counts of DISTINCT active entities (schools / students, not subscriptions)
    for the trailing `window_days` ending today (inclusive).

    Multiple subscriptions for the same entity are merged so an entity counts
    once per day. Uses a difference array + prefix sum.
    Returns {'labels': [...isodate], 'student': [...], 'institute': [...],
    'window_days': n}.
    """
    from collections import defaultdict
    n = window_days
    today = timezone.localdate()
    start_day = today - timedelta(days=n - 1)
    end_excl = today + timedelta(days=1)

    # Group spans per (panel, entity), so re-subscribes don't double-count.
    groups = defaultdict(list)
    for panel, key, start, end in intervals:
        if panel not in ('student', 'institute') or not start:
            continue
        groups[(panel, key)].append((start, end or end_excl))

    diffs = {'student': [0] * (n + 1), 'institute': [0] * (n + 1)}
    for (panel, _key), spans in groups.items():
        # Merge overlapping spans for this entity.
        merged = []
        for s, e in sorted(spans):
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        for s, e in merged:
            lo = max(s, start_day)
            hi = min(e, end_excl)
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


def _ts_to_local_date(ts):
    """Stripe epoch seconds -> date in the app's local timezone.

    Used for "today" comparisons so they line up with timezone.localdate()
    (the same "today" the dashboard header shows).
    """
    if not ts:
        return None
    return timezone.localtime(
        datetime.fromtimestamp(ts, dt_timezone.utc),
    ).date()


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
            md = s.get('metadata') or {}
            t = md.get('type')
            if t in STUDENT_TYPES:
                panel = 'student'
                key = md.get('user_id') or s.get('id')
            elif t in INSTITUTE_TYPES:
                panel = 'institute'
                key = md.get('school_id') or s.get('id')
            else:
                continue
            start = _ts_to_date(s.get('created'))
            end = _ts_to_date(s.get('ended_at') or s.get('canceled_at'))
            intervals.append((panel, key, start, end))
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
    for user_id, created, cancelled in Subscription.objects.values_list(
            'user_id', 'created_at', 'cancelled_at'):
        intervals.append((
            'student', user_id,
            timezone.localtime(created).date() if created else None,
            timezone.localtime(cancelled).date() if cancelled else None,
        ))
    for school_id, created in SchoolSubscription.objects.values_list(
            'school_id', 'created_at'):
        intervals.append((
            'institute', school_id,
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
