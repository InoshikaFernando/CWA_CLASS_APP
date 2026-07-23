"""Ops dashboard (superuser only): droplet health trends + incident timeline.

Data comes from OpsSnapshot rows recorded by the ``record_ops_metrics``
management command (droplet-side cron). Mirrors the finance / subscription
super-admin dashboards (dark theme, window selector, Chart.js).
"""
from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone
from django.views import View

# Single source of truth for the superuser gate (same as the usage dashboard).
from billing.views_admin import SuperuserRequiredMixin

from .models import OpsSnapshot
from .reporting import (
    get_ops_series, WINDOWS, DEFAULT_WINDOW, STALE_AFTER_MINUTES,
)


class OpsDashboardView(SuperuserRequiredMixin, View):
    def get(self, request):
        window = request.GET.get('window', DEFAULT_WINDOW)
        if window not in WINDOWS:
            window = DEFAULT_WINDOW

        series = get_ops_series(window)
        latest = OpsSnapshot.objects.order_by('-created_at').first()
        incidents = list(
            OpsSnapshot.objects.exclude(status=OpsSnapshot.STATUS_OK)
            .order_by('-created_at')[:20]
        )

        # Flag a stalled recorder: a snapshot older than the threshold means the
        # cron has likely stopped, so the "current" tiles are actually stale.
        latest_stale = bool(
            latest
            and latest.created_at
            < timezone.now() - timedelta(minutes=STALE_AFTER_MINUTES)
        )

        return render(request, 'admin_dashboard/ops/dashboard.html', {
            'latest': latest,
            'latest_stale': latest_stale,
            'stale_after_min': STALE_AFTER_MINUTES,
            'chart_data': series,
            'incidents': incidents,
            'window': window,
            # Granularity word for the chart subtitles ("per hour" for the 24h
            # view, "per day" for the longer ones) — the window key alone would
            # read "per day"/"per month", which misdescribes the buckets.
            'bucket_label': 'hour' if WINDOWS[window]['bucket'] == 'hour' else 'day',
            'window_options': [
                {'key': k, 'label': v['label']} for k, v in WINDOWS.items()
            ],
        })
