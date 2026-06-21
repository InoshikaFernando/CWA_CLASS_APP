"""Usage Analytics dashboard (superuser only).

A standalone, dark-themed monitoring page mirroring the Subscriptions Overview
dashboard. Renders six line charts from PageHit data:
  1. Active usage — last 24h, hourly
  2. Active usage — last 7 days, daily
  3. Active usage — last 30 days, daily
  4. Most-visited pages — daily, last 7 days
  5. Most-visited pages — daily, last 30 days
  6. 4xx / 5xx responses — last 30 days
"""
from django.shortcuts import render
from django.views import View

# Single source of truth for the superuser gate.
from billing.views_admin import SuperuserRequiredMixin
from . import reporting

REFRESH_SECONDS = 60


class UsageOverviewView(SuperuserRequiredMixin, View):
    def get(self, request):
        hourly_24 = reporting.active_usage_hourly(24)
        daily_7 = reporting.active_usage_daily(7)
        daily_30 = reporting.active_usage_daily(30)
        top_pages_7 = reporting.top_pages_daily(7)
        top_pages_30 = reporting.top_pages_daily(30)
        errors_30 = reporting.error_series_daily(30)
        active_now = reporting.active_now()

        # KPI tiles, derived from the series already computed (today = last bucket).
        views_today = daily_30['views'][-1] if daily_30['views'] else 0
        users_today = daily_30['users'][-1] if daily_30['users'] else 0
        errors_today = (
            (errors_30['client_4xx'][-1] if errors_30['client_4xx'] else 0)
            + (errors_30['server_5xx'][-1] if errors_30['server_5xx'] else 0)
        )
        views_24h = sum(hourly_24['views'])

        return render(request, 'admin_dashboard/usage/overview.html', {
            'hide_sidebar': True,
            'hide_footer': True,
            'refresh_seconds': REFRESH_SECONDS,
            'hourly_24': hourly_24,
            'daily_7': daily_7,
            'daily_30': daily_30,
            'top_pages_7': top_pages_7,
            'top_pages_30': top_pages_30,
            'errors_30': errors_30,
            'active_now': active_now,
            'kpi': {
                'views_today': views_today,
                'users_today': users_today,
                'errors_today': errors_today,
                'views_24h': views_24h,
            },
        })
