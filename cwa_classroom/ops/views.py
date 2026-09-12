"""Ops dashboard (superuser only): droplet health trends + incident timeline.

Data comes from OpsSnapshot rows recorded by the ``record_ops_metrics``
management command (droplet-side cron). Mirrors the finance / subscription
super-admin dashboards (dark theme, window selector, Chart.js).

Alongside the droplet metrics it carries the daily health checks whose failure
mode is silence rather than an error: email delivery (a stalled drain leaves
invoices "issued" but unsent), unpaid access (a delinquent account still using
the app because the paywall let it through), and scheduled publishing (homework
the automation built, sitting past its release time, never sent to the class).
"""
from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone
from django.views import View

# Single source of truth for the superuser gate (same as the usage dashboard).
from billing.views_admin import SuperuserRequiredMixin

from billing.stripe_health import (
    get_checkout_failure_health, get_stripe_price_health)
from billing.subscription_health import (
    get_payment_delay_health, get_unpaid_access_health)
from classroom.email_health import get_email_queue_health
from homework.publish_health import get_scheduled_publish_health

from .log_reader import DEFAULT_FILE, LEVELS, LOG_FILES, read_log
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

        # The other half of the same wall. The leak tile answers "is
        # anyone getting in without paying"; this one answers "is anyone
        # locked out without being told why", which is how six families
        # sat past due for weeks with a dashboard that showed a count and
        # nothing about whether it had been acted on.
        payment_delays = get_payment_delay_health()

        # A student who cannot pay at all. The two tiles are the same failure
        # seen from either end: `checkout_failures` is who already hit it,
        # `stripe_prices` is the misconfiguration waiting for the next person.
        # Both exist because an archived Stripe price took two weeks and an SSH
        # session to find, while the student saw only "contact support".
        checkout_failures = get_checkout_failure_health()
        stripe_prices = get_stripe_price_health()

        # The same silence again, on the teaching side. publish_scheduled_homework
        # is the only thing that makes a scheduled set visible to students, and
        # its cron drop-in is written by the one-time provisioning script rather
        # than by a deploy — so a droplet can run for months without it while
        # every question-schedule week is built, previewed, and never sent.
        scheduled_publish = get_scheduled_publish_health()

        return render(request, 'admin_dashboard/ops/dashboard.html', {
            'checkout_failures': checkout_failures,
            'scheduled_publish': scheduled_publish,
            'stripe_prices': stripe_prices,
            'latest': latest,
            'email_queue': email_queue,
            'unpaid_access': unpaid_access,
            'payment_delays': payment_delays,
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


class ErrorLogView(SuperuserRequiredMixin, View):
    """The application log, readable without an SSH session.

    Stripe told us exactly what was wrong with a student's checkout — "The
    price specified is inactive" — and that sentence lived only in
    /var/log/cwa/django-error.log. It took a shell on the droplet and a grep to
    find, two weeks after the student gave up. The ops tiles answer "is
    something broken"; this answers "what did it actually say".

    Superuser only, and deliberately: logs carry email addresses, usernames and
    request paths.
    """

    MAX_LIMIT = 500

    def get(self, request):
        key = request.GET.get('file', DEFAULT_FILE)
        level = request.GET.get('level', '')
        search = request.GET.get('q', '')
        try:
            limit = min(int(request.GET.get('limit', 200)), self.MAX_LIMIT)
        except (TypeError, ValueError):
            limit = 200

        entries, meta = read_log(key=key, level=level, search=search, limit=limit)

        return render(request, 'admin_dashboard/ops/error_log.html', {
            'entries': entries,
            'meta': meta,
            'files': LOG_FILES,
            'levels': LEVELS,
            'selected_file': meta['key'],
            'selected_level': (level or '').upper(),
            'search': search,
            'limit': limit,
        })
