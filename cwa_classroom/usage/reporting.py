"""Aggregation helpers for the Usage Analytics dashboard.

Buckets PageHit rows into hourly / daily series in Python (using the project's
local timezone) rather than DB-side Trunc functions, which keeps it correct on
MySQL without requiring the timezone tables to be loaded (those tables are not
loaded here — DB-side ``.dates()`` / ``TruncDate`` collapse to NULL).

Every series gap-fills empty buckets so charts show a continuous line at zero
rather than skipping quiet hours/days.

The dashboard uses the combined ``active_usage()`` / ``top_pages()`` entry
points, which read each window ONCE and derive the narrower sub-windows in
Python — far fewer full-table scans than one query per chart. The single-window
functions (``active_usage_daily`` etc.) remain as the shared building blocks.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone as dt_tz

from django.core.cache import cache
from django.utils import timezone

from .models import PageHit

CACHE_TTL = 60  # seconds — dashboard auto-refreshes, short cache is plenty
TOP_PAGES = 6
TOP_ERRORS = 12
ACTIVE_NOW_MINUTES = 5  # "active right now" window

# Path prefixes whose 4xx/5xx are browser/scanner noise, not app errors:
# Apple/Chrome icon + well-known probes, secret scanners, crawler files.
# Excluded from the headline error count + gauge + error chart so a real
# failure (e.g. /homework/12/take/) isn't buried under bot 404s. Still
# RECORDED and visible in the recent-errors drill-down (flagged as noise).
NOISE_PATH_PREFIXES = (
    '/apple-touch-icon',
    '/favicon',
    '/.well-known/',
    '/.env',
    '/robots.txt',
    '/sitemap',
)


def _is_noise(path):
    return path.startswith(NOISE_PATH_PREFIXES)


def _noise_filter():
    """Q matching noise paths, for `.exclude(...)` on a PageHit queryset."""
    from django.db.models import Q
    q = Q()
    for prefix in NOISE_PATH_PREFIXES:
        q |= Q(path__startswith=prefix)
    return q

# Distinct, readable colours for multi-line charts (top pages).
PAGE_COLORS = ['#34d399', '#818cf8', '#f472b6', '#fbbf24', '#22d3ee', '#a78bfa']


def _window_bounds(days):
    """(start_day, start_dt) for the trailing `days` ending today.

    Both are derived from a SINGLE localdate() read so the DB filter window and
    the Python bucket origin can't disagree if the clock crosses midnight
    between two reads. start_dt is 00:00 local on start_day.
    """
    start_day = timezone.localdate() - timedelta(days=days - 1)
    start_dt = timezone.make_aware(datetime.combine(start_day, time.min))
    return start_day, start_dt


# ---------------------------------------------------------------------------
# Shared bucketing helpers (operate on already-fetched rows)
# ---------------------------------------------------------------------------

def _daily_from_rows(rows, days, start_day):
    """rows: iterable of (created_at, user_id). Returns daily users/views."""
    views = [0] * days
    user_sets = [set() for _ in range(days)]
    for created_at, user_id in rows:
        idx = (timezone.localtime(created_at).date() - start_day).days
        if 0 <= idx < days:
            views[idx] += 1
            if user_id:
                user_sets[idx].add(user_id)
    labels = [(start_day + timedelta(days=k)).isoformat() for k in range(days)]
    return {'labels': labels, 'users': [len(s) for s in user_sets], 'views': views}


def _hourly_from_rows(rows, hours=24):
    """rows: iterable of (created_at, user_id). Returns hourly users/views for
    the trailing `hours`. Labels are derived from each bucket's true UTC instant
    converted to local time, so they stay aligned with the bucket indices across
    a DST transition (both are measured in real elapsed hours)."""
    now = timezone.localtime()
    end_hour = now.replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour - timedelta(hours=hours - 1)
    base_utc = start_hour.astimezone(dt_tz.utc)

    views = [0] * hours
    user_sets = [set() for _ in range(hours)]
    for created_at, user_id in rows:
        idx = int((timezone.localtime(created_at) - start_hour).total_seconds() // 3600)
        if 0 <= idx < hours:
            views[idx] += 1
            if user_id:
                user_sets[idx].add(user_id)

    labels = [timezone.localtime(base_utc + timedelta(hours=k)).strftime('%H:00')
              for k in range(hours)]
    return {'labels': labels, 'users': [len(s) for s in user_sets], 'views': views}


def _top_from_rows(rows, days, start_day, top_n):
    """rows: iterable of (created_at, path). Returns top-N path lines."""
    totals = defaultdict(int)
    per_path_day = defaultdict(lambda: [0] * days)
    for created_at, path in rows:
        idx = (timezone.localtime(created_at).date() - start_day).days
        if 0 <= idx < days:
            totals[path] += 1
            per_path_day[path][idx] += 1

    # Sort by hit count desc, then path asc — the path tie-break keeps the
    # selected set and their colours stable across 60s refreshes when several
    # paths are tied near the cutoff (otherwise lines flicker in/out).
    top = sorted(totals, key=lambda p: (-totals[p], p))[:top_n]
    labels = [(start_day + timedelta(days=k)).isoformat() for k in range(days)]
    series = [
        {'path': p, 'color': PAGE_COLORS[i % len(PAGE_COLORS)], 'data': per_path_day[p]}
        for i, p in enumerate(top)
    ]
    return {'labels': labels, 'series': series}


# ---------------------------------------------------------------------------
# Live "active now"
# ---------------------------------------------------------------------------

def active_now(minutes=ACTIVE_NOW_MINUTES):
    """Who's active right now, in the last `minutes`:
      * users  — distinct logged-in users
      * guests — distinct anonymous visitors (by client_key = hashed IP+UA)
      * views  — total page views

    Not cached — it should reflect the latest moment; it's a cheap indexed
    count over a tiny window.
    """
    since = timezone.now() - timedelta(minutes=minutes)
    qs = PageHit.objects.filter(created_at__gte=since)
    users = qs.exclude(user__isnull=True).values('user_id').distinct().count()
    guests = (qs.filter(user__isnull=True).exclude(client_key='')
              .values('client_key').distinct().count())
    return {
        'minutes': minutes,
        'users': users,
        'guests': guests,
        'views': qs.count(),
    }


# ---------------------------------------------------------------------------
# Combined entry points used by the dashboard (one DB scan per category)
# ---------------------------------------------------------------------------

def active_usage(days=30):
    """Active users + page views as hourly-24h, daily-7 and daily-`days`
    series, derived from a SINGLE scan of the last `days` of rows."""
    cache_key = f'usage:active:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_day, start_dt = _window_bounds(days)
    rows = list(PageHit.objects.filter(created_at__gte=start_dt)
                .values_list('created_at', 'user_id'))

    daily_full = _daily_from_rows(rows, days, start_day)
    daily7 = {k: v[-7:] for k, v in daily_full.items()}
    hourly24 = _hourly_from_rows(rows, 24)

    result = {'hourly24': hourly24, 'daily7': daily7, 'daily30': daily_full}
    cache.set(cache_key, result, CACHE_TTL)
    return result


def top_pages(days=30, top_n=TOP_PAGES):
    """Most-visited pages over 7 and `days`-day windows, from one scan. The
    7-day top-N is recomputed from the subset (a page hot this week may not be
    hot over 30 days), so it is not just a slice of the 30-day lines."""
    # NOTE: distinct from the old single-window key ('usage:toppages:...') and
    # from top_pages_daily ('usage:toppages1:...') — this returns a different
    # shape ({d7,d30}), so it must never read a value written under those keys.
    cache_key = f'usage:toppages_combined:{days}:{top_n}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_day, start_dt = _window_bounds(days)
    rows = list(PageHit.objects.filter(
        created_at__gte=start_dt, status_code__lt=400,
    ).values_list('created_at', 'path'))

    d_full = _top_from_rows(rows, days, start_day, top_n)
    # Derive the 7-day origin from the same start_day snapshot (no 2nd
    # localdate read): start_day + (days-7) == today - 6.
    start_day7 = start_day + timedelta(days=days - 7)
    rows7 = [(c, p) for (c, p) in rows
             if timezone.localtime(c).date() >= start_day7]
    d7 = _top_from_rows(rows7, 7, start_day7, top_n)

    result = {'d7': d7, 'd30': d_full}
    cache.set(cache_key, result, CACHE_TTL)
    return result


# ---------------------------------------------------------------------------
# Single-window building blocks (kept for direct/unit use)
# ---------------------------------------------------------------------------

def active_usage_hourly(hours=24):
    """Distinct active users and total page views per hour for the last `hours`."""
    cache_key = f'usage:hourly:{hours}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    rows = PageHit.objects.filter(
        created_at__gte=timezone.now() - timedelta(hours=hours),
    ).values_list('created_at', 'user_id')
    result = _hourly_from_rows(rows, hours)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def active_usage_daily(days):
    """Distinct active users and total page views per day for the last `days`."""
    cache_key = f'usage:daily:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    start_day, start_dt = _window_bounds(days)
    rows = PageHit.objects.filter(
        created_at__gte=start_dt,
    ).values_list('created_at', 'user_id')
    result = _daily_from_rows(rows, days, start_day)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def top_pages_daily(days, top_n=TOP_PAGES):
    """Per-day hit counts for the `top_n` most-visited paths over the window."""
    cache_key = f'usage:toppages1:{days}:{top_n}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    start_day, start_dt = _window_bounds(days)
    rows = PageHit.objects.filter(
        created_at__gte=start_dt, status_code__lt=400,
    ).values_list('created_at', 'path')
    result = _top_from_rows(rows, days, start_day, top_n)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def error_series_daily(days=30):
    """Per-day 4xx and 5xx counts plus a table of the top failing paths."""
    cache_key = f'usage:errors:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_day, start_dt = _window_bounds(days)
    client_4xx = [0] * days
    server_5xx = [0] * days
    err_totals = defaultdict(int)
    rows = PageHit.objects.filter(
        created_at__gte=start_dt, status_code__gte=400,
    ).exclude(_noise_filter()).values_list('created_at', 'path', 'status_code')
    for created_at, path, status in rows:
        idx = (timezone.localtime(created_at).date() - start_day).days
        if not (0 <= idx < days):
            continue
        if status >= 500:
            server_5xx[idx] += 1
        else:
            client_4xx[idx] += 1
        err_totals[(path, status)] += 1

    top_errors = [
        {'path': path, 'status': status, 'count': count}
        for (path, status), count in sorted(
            err_totals.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_ERRORS]
    ]
    labels = [(start_day + timedelta(days=k)).isoformat() for k in range(days)]
    result = {
        'labels': labels,
        'client_4xx': client_4xx,
        'server_5xx': server_5xx,
        'top_errors': top_errors,
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result


# ---------------------------------------------------------------------------
# Health summary (gauge + donut) and error drill-down
# ---------------------------------------------------------------------------

# Error-rate gauge thresholds (percent): < OK_MAX green, < WARN_MAX amber, else red.
ERROR_RATE_OK_MAX = 1.0
ERROR_RATE_WARN_MAX = 5.0


def health_summary(days=30):
    """Single-scan status breakdown for the gauge + donut:
      * ok / client_4xx / server_5xx — counts by status class over the window
      * total / errors / error_rate  — for the error-rate gauge
      * band                         — 'ok' | 'warn' | 'bad' for gauge colour

    One COUNT-style scan (status_code only); cached like the other series.
    """
    cache_key = f'usage:health:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    _start_day, start_dt = _window_bounds(days)
    ok = client_4xx = server_5xx = noise = 0
    for status, path in PageHit.objects.filter(
            created_at__gte=start_dt).values_list('status_code', 'path'):
        if status >= 400 and _is_noise(path):
            noise += 1            # bot/scanner 404s — kept out of the gauge
        elif status >= 500:
            server_5xx += 1
        elif status >= 400:
            client_4xx += 1
        else:
            ok += 1

    errors = client_4xx + server_5xx
    total = ok + errors           # excludes noise from the rate denominator
    rate = (errors / total * 100) if total else 0.0
    band = ('ok' if rate < ERROR_RATE_OK_MAX
            else 'warn' if rate < ERROR_RATE_WARN_MAX else 'bad')
    result = {
        'ok': ok, 'client_4xx': client_4xx, 'server_5xx': server_5xx,
        'noise': noise, 'total': total, 'errors': errors,
        'error_rate': round(rate, 2), 'band': band,
        'warn_max': ERROR_RATE_WARN_MAX,
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result


def recent_errors(limit=50, days=30):
    """The most recent individual error hits for the drill-down: each is
    {when (local 'MM-DD HH:MM'), status, path, user}. Newest first. Not the
    same as error_series_daily's aggregate — this answers "what were they?"."""
    _start_day, start_dt = _window_bounds(days)
    rows = (PageHit.objects.filter(created_at__gte=start_dt, status_code__gte=400)
            .select_related('user').order_by('-created_at')[:limit])
    out = []
    for h in rows:
        out.append({
            'when': timezone.localtime(h.created_at).strftime('%d %b %H:%M'),
            'status': h.status_code,
            'path': h.path,
            'user': getattr(h.user, 'username', '') or '—',
            'noise': _is_noise(h.path),
        })
    return out
