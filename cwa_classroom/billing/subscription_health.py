"""
Unpaid-access health — one source of truth for "is anyone still using the app
while their subscription is delinquent?".

Consumed by the ops dashboard, the deep health endpoint, and the
``check_unpaid_access`` alert command, so all three agree on what a leak is
rather than each re-deriving it. Mirrors ``classroom.email_health``.

Background: ``TrialExpiryMiddleware`` is the only thing standing between a
delinquent account (card failed / cancelled / expired) and the whole app. A
regression in that gate does not error — the user simply keeps working and
nobody is billed. The only evidence is in the ``usage.PageHit`` log: a 200 on a
restricted path by a user whose subscription is delinquent. This module reads
that evidence so the failure is visible on a dashboard within a day rather than
at the next revenue review.
"""
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from cwa_classroom.middleware import TrialExpiryMiddleware

# Paths a gated user is legitimately allowed to reach (the middleware's own
# allow-list, plus onboarding/static that never count as "restricted"). Derived
# from the middleware rather than copied so the two cannot drift: a path the
# middleware starts allowing must stop counting as a leak on the same commit.
ALLOWED_PREFIXES = TrialExpiryMiddleware.ALLOWED_PATHS + (
    '/accounts/complete-profile/', '/accounts/blocked/', '/accounts/login/',
    '/static/', '/media/', '/favicon',
)

# Subscription states that mean "this account should be behind the wall".
# Spelled out rather than imported so this module needs no model import at
# import time; billing/tests_unpaid_access_health.py fails if it ever drifts
# from Subscription's own constants.
DELINQUENT = ('past_due', 'expired', 'cancelled')

# How far back the dashboard and the daily cron look by default.
DEFAULT_LOOKBACK_DAYS = 7

# A leak whose newest hit is within this many hours is still happening — the
# gate is open right now. An older one inside the window is a leak that has
# already been closed (or the user gave up), which is worth showing but is not
# an emergency.
ACTIVE_LEAK_HOURS = 24

# Cap on the per-user detail rows. The count is always exact; only the listing
# is trimmed, so a pathological number of delinquent accounts cannot turn one
# dashboard render into hundreds of queries.
MAX_LEAK_ROWS = 25

STATUS_OK = 'ok'
STATUS_WARNING = 'warning'
STATUS_CRITICAL = 'critical'


def is_restricted(path):
    """True when `path` is somewhere a delinquent account should not reach."""
    return not any(path.startswith(p) for p in ALLOWED_PREFIXES)


def get_unpaid_access_health(days=DEFAULT_LOOKBACK_DAYS, now=None, username=None):
    """Return a dict describing unpaid-access health. Never raises on empty data.

    Keys:
        status          'ok' | 'warning' | 'critical'
        reasons         list[str] — why it is not ok (empty when ok)
        window_days     int   — the lookback actually used
        since           datetime — start of that window
        delinquent      int   — active accounts with a delinquent subscription
        leak_count      int   — how many of them reached a restricted page
        hit_count       int   — restricted page views across all of them
        last_seen_at    datetime | None — newest restricted hit
        last_seen_min   int | None — minutes since that hit
        active_leak     bool  — a hit within ACTIVE_LEAK_HOURS (gate open now)
        leaks           list[dict] — per-user detail, newest first, capped at
                        MAX_LEAK_ROWS: username, name, status, count,
                        last_seen, last_path
        truncated       bool  — True when `leaks` is shorter than leak_count
    """
    from usage.models import PageHit

    from .models import Subscription

    now = now or timezone.now()
    days = max(1, int(days or DEFAULT_LOOKBACK_DAYS))
    since = now - timedelta(days=days)

    subs = Subscription.objects.select_related('user').filter(
        status__in=DELINQUENT, user__is_active=True,
    )
    if username:
        subs = subs.filter(user__username=username)
    sub_by_user_id = {sub.user_id: sub for sub in subs}

    empty = {
        'status': STATUS_OK,
        'reasons': [],
        'window_days': days,
        'since': since,
        'delinquent': len(sub_by_user_id),
        'leak_count': 0,
        'hit_count': 0,
        'last_seen_at': None,
        'last_seen_min': None,
        'active_leak': False,
        'leaks': [],
        'truncated': False,
    }
    if not sub_by_user_id:
        return empty

    # One aggregate query for every delinquent user at once. The allow-list is
    # applied in SQL so a chatty account cannot pull its whole hit log into
    # Python just to have it filtered away.
    hits = PageHit.objects.filter(
        user_id__in=sub_by_user_id, status_code=200, created_at__gte=since,
    )
    for prefix in ALLOWED_PREFIXES:
        hits = hits.exclude(path__startswith=prefix)

    rows = list(
        hits.values('user_id')
        .annotate(count=Count('id'), last_seen=Max('created_at'))
        .order_by('-last_seen')
    )
    if not rows:
        return empty

    leaks = []
    for row in rows[:MAX_LEAK_ROWS]:
        sub = sub_by_user_id[row['user_id']]
        last_path = (
            hits.filter(user_id=row['user_id'])
            .order_by('-created_at')
            .values_list('path', flat=True)
            .first()
        ) or ''
        leaks.append({
            'username': sub.user.username,
            'name': sub.user.get_full_name() or sub.user.username,
            'status': sub.status,
            'count': row['count'],
            'last_seen': row['last_seen'],
            'last_path': last_path,
        })

    hit_count = sum(row['count'] for row in rows)
    last_seen_at = rows[0]['last_seen']
    last_seen_min = int((now - last_seen_at).total_seconds() // 60)
    active_leak = last_seen_at >= now - timedelta(hours=ACTIVE_LEAK_HOURS)

    if active_leak:
        status = STATUS_CRITICAL
        reasons = [
            f'{len(rows)} delinquent account(s) reached restricted pages in '
            f'the last {ACTIVE_LEAK_HOURS} hours — the paywall is open'
        ]
    else:
        status = STATUS_WARNING
        reasons = [
            f'{len(rows)} delinquent account(s) reached restricted pages in '
            f'the last {days} day(s); newest was {_humanise(last_seen_min)} ago'
        ]

    return {
        'status': status,
        'reasons': reasons,
        'window_days': days,
        'since': since,
        'delinquent': len(sub_by_user_id),
        'leak_count': len(rows),
        'hit_count': hit_count,
        'last_seen_at': last_seen_at,
        'last_seen_min': last_seen_min,
        'active_leak': active_leak,
        'leaks': leaks,
        'truncated': len(rows) > len(leaks),
    }


def _humanise(minutes):
    """'45 minutes' / '3.2 hours' / '11 days' — readable at every scale."""
    if minutes < 60:
        return f'{minutes} minutes'
    if minutes < 60 * 48:
        return f'{minutes / 60:.1f} hours'
    return f'{minutes / 1440:.1f} days'
