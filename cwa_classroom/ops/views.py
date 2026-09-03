"""Ops dashboard (superuser only): droplet health trends + incident timeline.

Data comes from OpsSnapshot rows recorded by the ``record_ops_metrics``
management command (droplet-side cron). Mirrors the finance / subscription
super-admin dashboards (dark theme, window selector, Chart.js).

Alongside the droplet metrics it carries the two daily health checks whose
failure mode is silence rather than an error: email delivery (a stalled drain
leaves invoices "issued" but unsent) and unpaid access (a delinquent account
still using the app because the paywall let it through).
"""
from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone
from django.views import View

# Single source of truth for the superuser gate (same as the usage dashboard).
from billing.views_admin import SuperuserRequiredMixin

from billing.subscription_health import get_unpaid_access_health
from classroom.email_health import get_email_queue_health

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

        # Email delivery is a droplet-health signal like any other cron: when
        # the drain stops, invoices are marked issued and silently never sent.
        # Surfaced here so a stalled queue is visible in minutes rather than the
        # ten weeks it went unnoticed in 2026.
        email_queue = get_email_queue_health()

        # Same class of silent failure on the billing side: when the paywall
        # lets a delinquent account through, nothing errors and nobody is
        # billed — the only evidence is the page hits below. The daily
        # check_unpaid_access cron alerts on it; this tile is where it is
        # visible without reading a Discord channel.
        unpaid_access = get_unpaid_access_health()

        return render(request, 'admin_dashboard/ops/dashboard.html', {
            'latest': latest,
            'email_queue': email_queue,
            'unpaid_access': unpaid_access,
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
