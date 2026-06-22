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
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

import requests
import stripe
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes — avoid hitting Stripe on every page load
_CENTS = Decimal('100')

# FX rates move slowly; cache for 12h so the dashboard / sync never hammer the
# free FX API. Key is provider-agnostic (USD->NZD only).
FX_CACHE_TTL = 60 * 60 * 12
FX_CACHE_KEY = 'fx:usd_nzd'


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
    """Daily active-subscriptions graph from the local DB — PAYING + TRIAL only.

    Both lines exclude "free" / no-package actives so the graph tracks the
    meaningful subscriber trend rather than every account:
      * paying = a priced package / plan (price > 0)
      * trial  = status 'trialing'
    Students come from billing.Subscription (span ends at cancelled_at);
    institutes from SchoolSubscription, restricted to active/trialing (it has
    no cancel timestamp, so a cancelled one would otherwise read as live
    forever).
    """
    from django.db.models import Q
    if window_days not in DAILY_WINDOWS:
        window_days = 30
    from billing.models import Subscription, SchoolSubscription
    intervals = []
    student_qs = Subscription.objects.filter(
        Q(package__isnull=False, package__price__gt=0) | Q(status='trialing'),
    )
    for user_id, created, cancelled in student_qs.values_list(
            'user_id', 'created_at', 'cancelled_at'):
        intervals.append((
            'student', user_id,
            timezone.localtime(created).date() if created else None,
            timezone.localtime(cancelled).date() if cancelled else None,
        ))
    institute_qs = SchoolSubscription.objects.filter(
        status__in=['active', 'trialing'],
    ).filter(
        Q(plan__isnull=False, plan__price__gt=0) | Q(status='trialing'),
    )
    for school_id, created in institute_qs.values_list(
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


# ---------------------------------------------------------------------------
# Income vs Expense (operating-cost dashboard)
# ---------------------------------------------------------------------------

def _first_of_month(d):
    """Date -> first day of its month."""
    return d.replace(day=1)


def _add_month(d):
    """First-of-month date -> first day of the following month."""
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


def _month_dt(d):
    """Local date -> aware datetime at 00:00 (for Stripe period bounds)."""
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def get_income_expense_summary(months=6):
    """Monthly income (paid Stripe revenue) vs operating expenses, in NZD.

    Builds a `months`-long series ending with the current month. Income per
    month is the sum of paid student + institute subscription invoices
    (`get_paid_revenue`, Stripe-sourced, cached). Expenses per month are the
    sum of local `Expense.amount` rows booked in that month.

    Returns {
      'months': [
        {'label': 'Jun 2026', 'start': date, 'income': Decimal,
         'expense': Decimal, 'net': Decimal}, ...   # oldest -> newest
      ],
      'category_totals': [{'category': key, 'label': str, 'amount': Decimal}, ...],
      'totals': {'income': Decimal, 'expense': Decimal, 'net': Decimal},
      'income_available': bool,          # False if Stripe was unreachable
      'max_value': Decimal,              # for chart scaling
    }
    """
    from .models import Expense, ExpenseCategory

    months = max(1, min(int(months), 24))
    today = timezone.localdate()
    current = _first_of_month(today)

    # Oldest-first list of month-start dates.
    starts = []
    m = current
    for _ in range(months):
        starts.append(m)
        if m.month == 1:
            m = m.replace(year=m.year - 1, month=12)
        else:
            m = m.replace(month=m.month - 1)
    starts.reverse()

    range_start = starts[0]
    range_end = _add_month(current)

    # All expenses in the window, pulled once and bucketed in Python.
    expense_rows = (
        Expense.objects.filter(
            incurred_on__gte=range_start, incurred_on__lt=range_end,
        )
        .values('incurred_on', 'category', 'amount')
    )
    ZERO = Decimal('0.00')
    expense_by_month = {}
    category_totals = {}
    for row in expense_rows:
        key = _first_of_month(row['incurred_on'])
        expense_by_month[key] = expense_by_month.get(key, ZERO) + row['amount']
        category_totals[row['category']] = (
            category_totals.get(row['category'], ZERO) + row['amount']
        )

    income_available = True
    series = []
    total_income = ZERO
    total_expense = ZERO
    max_value = ZERO
    for start in starts:
        nxt = _add_month(start)
        income = ZERO
        if income_available:
            try:
                rev = get_paid_revenue(_month_dt(start), _month_dt(nxt))
                income = rev['student'] + rev['institute']
            except StripeUnavailable:
                income_available = False
        expense = expense_by_month.get(start, ZERO)
        series.append({
            'label': start.strftime('%b %Y'),
            'start': start,
            'income': income,
            'expense': expense,
            'net': income - expense,
        })
        total_income += income
        total_expense += expense
        max_value = max(max_value, income, expense)

    cat_labels = dict(ExpenseCategory.choices)
    cat_list = [
        {'category': k, 'label': cat_labels.get(k, k), 'amount': v}
        for k, v in sorted(
            category_totals.items(), key=lambda kv: kv[1], reverse=True,
        )
    ]

    return {
        'months': series,
        'category_totals': cat_list,
        'totals': {
            'income': total_income,
            'expense': total_expense,
            'net': total_income - total_expense,
        },
        'income_available': income_available,
        'max_value': max_value,
    }


def get_usd_to_nzd_rate():
    """Current USD->NZD rate for converting USD-billed costs to NZD.

    Fetches from a free, ECB-backed, key-less FX API (settings.FX_RATE_API_URL,
    frankfurter.app by default), caches it for FX_CACHE_TTL, and falls back to
    the static settings.USD_TO_NZD_RATE when the API is disabled / unreachable /
    malformed. Always returns a positive Decimal — never raises, so callers can
    use it inline.

    Returns (Decimal rate, str source) where source is 'live' | 'cache' |
    'fallback' so the UI can show where the number came from.
    """
    fallback = Decimal(str(getattr(settings, 'USD_TO_NZD_RATE', 1.65)))

    cached = cache.get(FX_CACHE_KEY)
    if cached is not None:
        return cached, 'cache'

    url = getattr(settings, 'FX_RATE_API_URL', '')
    if not url:
        return fallback, 'fallback'

    try:
        resp = requests.get(
            url, params={'from': 'USD', 'to': 'NZD'}, timeout=10,
        )
        resp.raise_for_status()
        rate = Decimal(str(resp.json()['rates']['NZD']))
        if rate <= 0:
            raise ValueError(f'non-positive FX rate {rate}')
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        logger.warning(
            'USD->NZD FX fetch failed, using fallback %s: %s', fallback, exc)
        return fallback, 'fallback'

    cache.set(FX_CACHE_KEY, rate, FX_CACHE_TTL)
    return rate, 'live'


def sync_ai_usage_expenses():
    """Mirror the internal AI cost ledger into monthly Anthropic Expense rows.

    Sums `taskqueue.AIUsageLog.est_cost_usd` per calendar month — covering EVERY
    AI source (ai_import PDF scan, homework marking, worksheet classification) —
    converts USD->NZD and upserts one `claude_api` Expense row per month. Because
    it reads the ledger, any new AI feature that logs usage is captured with no
    config change. Idempotent; returns rows created/updated.
    """
    from .models import (
        Expense, ExpenseCategory, EXPENSE_SOURCE_AI_GRADING,
    )
    from taskqueue.models import AIUsageLog

    rate, _ = get_usd_to_nzd_rate()

    # Bucket by calendar month in Python — avoids MySQL TruncMonth, which needs
    # the server's timezone tables loaded when USE_TZ is on.
    buckets = {}
    rows = AIUsageLog.objects.values_list('created_at', 'est_cost_usd')
    for created_at, cost in rows.iterator():
        if not cost or cost <= 0:
            continue
        local = (
            timezone.localtime(created_at)
            if timezone.is_aware(created_at) else created_at
        )
        key = _first_of_month(local.date())
        buckets[key] = buckets.get(key, Decimal('0')) + cost

    touched = 0
    for month_start, usd in sorted(buckets.items()):
        nzd = (usd * rate).quantize(Decimal('0.01'))
        Expense.objects.update_or_create(
            source=EXPENSE_SOURCE_AI_GRADING,
            incurred_on=month_start,
            defaults={
                'category': ExpenseCategory.CLAUDE_API,
                'vendor': 'Anthropic',
                'description': 'AI usage: PDF scan + marking + worksheets (auto)',
                'amount': nzd,
                'original_amount': usd.quantize(Decimal('0.000001')),
                'original_currency': 'USD',
            },
        )
        touched += 1
    return touched


def sync_digitalocean_expenses():
    """Pull real DigitalOcean monthly invoices into Expense rows (NZD).

    No-op unless settings.DIGITALOCEAN_API_TOKEN is set. Reads the invoices
    endpoint, so every line item (droplets, DBs, Spaces, bandwidth, any addon)
    is included automatically — no manual update when infra changes. For each
    month it writes the actual invoice, it removes any `recurring` DigitalOcean
    estimate for that month so the two never double-count. Idempotent. Returns
    the number of invoice rows created/updated (0 when the token is unset).
    """
    from .models import (
        Expense, ExpenseCategory, RecurringExpense,
        EXPENSE_SOURCE_DIGITALOCEAN, EXPENSE_SOURCE_RECURRING,
    )

    token = getattr(settings, 'DIGITALOCEAN_API_TOKEN', '')
    if not token:
        return 0

    try:
        resp = requests.get(
            'https://api.digitalocean.com/v2/customers/my/invoices',
            headers={'Authorization': f'Bearer {token}'},
            params={'per_page': 50},
            timeout=15,
        )
        resp.raise_for_status()
        invoices = resp.json().get('invoices', [])
    except (requests.RequestException, ValueError) as exc:
        logger.warning('DigitalOcean invoice fetch failed: %s', exc)
        return 0

    rate, _ = get_usd_to_nzd_rate()
    touched = 0
    for inv in invoices:
        # invoice_period is "YYYY-MM"; amount is a USD decimal string.
        period = (inv.get('invoice_period') or '').strip()
        try:
            year, month = (int(p) for p in period.split('-')[:2])
            month_start = date(year, month, 1)
            usd = Decimal(str(inv.get('amount', '0')))
        except (ValueError, TypeError, InvalidOperation) as exc:
            logger.warning('Skipping DO invoice %r: %s', inv, exc)
            continue
        if usd <= 0:
            continue
        nzd = (usd * rate).quantize(Decimal('0.01'))
        Expense.objects.update_or_create(
            source=EXPENSE_SOURCE_DIGITALOCEAN,
            incurred_on=month_start,
            defaults={
                'category': ExpenseCategory.DIGITALOCEAN,
                'vendor': 'DigitalOcean',
                'description': f'Invoice {period} (auto)',
                'amount': nzd,
                'original_amount': usd.quantize(Decimal('0.01')),
                'original_currency': 'USD',
            },
        )
        # Actual supersedes any recurring estimate for the same month.
        Expense.objects.filter(
            category=ExpenseCategory.DIGITALOCEAN,
            source=EXPENSE_SOURCE_RECURRING,
            incurred_on=month_start,
        ).delete()
        touched += 1
    return touched
