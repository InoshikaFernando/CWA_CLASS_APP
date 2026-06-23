"""Usage Analytics dashboard (superuser only).

A standalone, dark-themed monitoring page mirroring the Subscriptions Overview
dashboard. At-a-glance health + usage from PageHit data:
  * Health banner (error-rate verdict) + KPI tiles + live "active now"
  * One active-usage trend chart with a 24h / 7d / 30d toggle
  * Errors 4xx/5xx (30d) with an alert threshold
  * Most-visited pages as a ranked bar list (7d / 30d)
  * Recent-errors + top-failing-pages drill-downs (below the fold)
"""
from django.shortcuts import render
from django.views import View

# Single source of truth for the superuser gate.
from billing.views_admin import SuperuserRequiredMixin
from . import reporting

REFRESH_SECONDS = 60


def _ranked_pages(series):
    """Collapse a top-pages multi-line series into a ranked list of
    {path, total} (sum of each path's per-day hits), busiest first."""
    rows = [{'path': s['path'], 'total': sum(s['data'])} for s in series]
    rows.sort(key=lambda r: -r['total'])
    return rows


class UsageOverviewView(SuperuserRequiredMixin, View):
    def get(self, request):
        # Combined entry points: one DB scan for the three active-usage charts
        # and one for the two top-pages charts (instead of a query per chart).
        usage = reporting.active_usage(30)
        pages = reporting.top_pages(30)
        hourly_24 = usage['hourly24']
        daily_7 = usage['daily7']
        daily_30 = usage['daily30']
        top_pages_7 = pages['d7']
        top_pages_30 = pages['d30']
        errors_30 = reporting.error_series_daily(30)
        active_now = reporting.active_now()
        health = reporting.health_summary(30)
        recent_errors = reporting.recent_errors(limit=50)

        # KPI tiles, derived from the series already computed (today = last bucket).
        views_today = daily_30['views'][-1] if daily_30['views'] else 0
        users_today = daily_30['users'][-1] if daily_30['users'] else 0
        errors_today = (
            (errors_30['client_4xx'][-1] if errors_30['client_4xx'] else 0)
            + (errors_30['server_5xx'][-1] if errors_30['server_5xx'] else 0)
        )
        views_24h = sum(hourly_24['views'])

        # Ranked top-pages bar lists (from the data already fetched — no query).
        ranked_30 = _ranked_pages(top_pages_30['series'])
        ranked_7 = _ranked_pages(top_pages_7['series'])
        ranked_max = ranked_30[0]['total'] if ranked_30 else 0

        return render(request, 'admin_dashboard/usage/overview.html', {
            'hide_sidebar': True,
            'hide_footer': True,
            'refresh_seconds': REFRESH_SECONDS,
            'hourly_24': hourly_24,
            'daily_7': daily_7,
            'daily_30': daily_30,
            'top_pages_7': top_pages_7,
            'top_pages_30': top_pages_30,
            'ranked_30': ranked_30,
            'ranked_7': ranked_7,
            'ranked_max': ranked_max,
            'errors_30': errors_30,
            'active_now': active_now,
            'health': health,
            'recent_errors': recent_errors,
            'kpi': {
                'views_today': views_today,
                'users_today': users_today,
                'errors_today': errors_today,
                'views_24h': views_24h,
            },
        })
