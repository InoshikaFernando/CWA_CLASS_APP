"""Aggregation helpers for the Usage Analytics dashboard.

Buckets PageHit rows into hourly / daily series in Python (using the project's
local timezone) rather than DB-side Trunc functions, which keeps it correct on
MySQL without requiring the timezone tables to be loaded.

Every series gap-fills empty buckets so charts show a continuous line at zero
rather than skipping quiet hours/days.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import PageHit

CACHE_TTL = 60  # seconds — dashboard auto-refreshes, short cache is plenty
TOP_PAGES = 6
TOP_ERRORS = 12
ACTIVE_NOW_MINUTES = 5  # "active right now" window

# Distinct, readable colours for multi-line charts (top pages).
PAGE_COLORS = ['#34d399', '#818cf8', '#f472b6', '#fbbf24', '#22d3ee', '#a78bfa']


def _window_start_dt(days):
    """Aware datetime at 00:00 local, (days-1) days before today."""
    start_day = timezone.localdate() - timedelta(days=days - 1)
    return timezone.make_aware(datetime.combine(start_day, time.min))


def active_now(minutes=ACTIVE_NOW_MINUTES):
    """Who's active right now, in the last `minutes`:
      * users  — distinct logged-in users
      * guests — distinct anonymous sessions (by session_key)
      * views  — total page views

    Not cached — it should reflect the latest moment; it's a cheap indexed
    count over a tiny window. Note: a guest is only counted once Django has a
    session_key for them, so guests can under-count logged-out traffic.
    """
    since = timezone.now() - timedelta(minutes=minutes)
    qs = PageHit.objects.filter(created_at__gte=since)
    users = qs.exclude(user__isnull=True).values('user_id').distinct().count()
    guests = (qs.filter(user__isnull=True).exclude(session_key='')
              .values('session_key').distinct().count())
    return {
        'minutes': minutes,
        'users': users,
        'guests': guests,
        'views': qs.count(),
    }


def active_usage_hourly(hours=24):
    """Distinct active users and total page views per hour for the last `hours`."""
    cache_key = f'usage:hourly:{hours}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = timezone.localtime()
    end_hour = now.replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour - timedelta(hours=hours - 1)
    start_utc = start_hour  # already aware

    views = [0] * hours
    user_sets = [set() for _ in range(hours)]
    for created_at, user_id in PageHit.objects.filter(
            created_at__gte=start_utc).values_list('created_at', 'user_id'):
        local = timezone.localtime(created_at)
        idx = int((local - start_hour).total_seconds() // 3600)
        if 0 <= idx < hours:
            views[idx] += 1
            if user_id:
                user_sets[idx].add(user_id)

    labels = [(start_hour + timedelta(hours=k)).strftime('%H:00') for k in range(hours)]
    result = {
        'labels': labels,
        'users': [len(s) for s in user_sets],
        'views': views,
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result


def active_usage_daily(days):
    """Distinct active users and total page views per day for the last `days`."""
    cache_key = f'usage:daily:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_day = timezone.localdate() - timedelta(days=days - 1)
    start_dt = _window_start_dt(days)

    views = [0] * days
    user_sets = [set() for _ in range(days)]
    for created_at, user_id in PageHit.objects.filter(
            created_at__gte=start_dt).values_list('created_at', 'user_id'):
        idx = (timezone.localtime(created_at).date() - start_day).days
        if 0 <= idx < days:
            views[idx] += 1
            if user_id:
                user_sets[idx].add(user_id)

    labels = [(start_day + timedelta(days=k)).isoformat() for k in range(days)]
    result = {
        'labels': labels,
        'users': [len(s) for s in user_sets],
        'views': views,
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result


def top_pages_daily(days, top_n=TOP_PAGES):
    """Per-day hit counts for the `top_n` most-visited paths over the window.

    Returns {'labels': [...iso dates], 'series': [{'path','color','data':[...]}]}.
    """
    cache_key = f'usage:toppages:{days}:{top_n}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_day = timezone.localdate() - timedelta(days=days - 1)
    start_dt = _window_start_dt(days)

    totals = defaultdict(int)
    per_path_day = defaultdict(lambda: [0] * days)
    rows = PageHit.objects.filter(
        created_at__gte=start_dt, status_code__lt=400,
    ).values_list('created_at', 'path')
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
        {
            'path': path,
            'color': PAGE_COLORS[i % len(PAGE_COLORS)],
            'data': per_path_day[path],
        }
        for i, path in enumerate(top)
    ]
    result = {'labels': labels, 'series': series}
    cache.set(cache_key, result, CACHE_TTL)
    return result


def error_series_daily(days=30):
    """Per-day 4xx and 5xx counts plus a table of the top failing paths."""
    cache_key = f'usage:errors:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_day = timezone.localdate() - timedelta(days=days - 1)
    start_dt = _window_start_dt(days)

    client_4xx = [0] * days
    server_5xx = [0] * days
    err_totals = defaultdict(int)
    rows = PageHit.objects.filter(
        created_at__gte=start_dt, status_code__gte=400,
    ).values_list('created_at', 'path', 'status_code')
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
            err_totals.items(), key=lambda kv: kv[1], reverse=True)[:TOP_ERRORS]
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
