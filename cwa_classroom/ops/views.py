"""Ops dashboard (superuser only): droplet health trends + incident timeline.

Data comes from OpsSnapshot rows recorded by the ``record_ops_metrics``
management command (droplet-side cron). Mirrors the finance / subscription
super-admin dashboards (dark theme, window selector, Chart.js).
"""
from django.shortcuts import render
from django.views import View

# Single source of truth for the superuser gate (same as the usage dashboard).
from billing.views_admin import SuperuserRequiredMixin

from .models import OpsSnapshot
from .reporting import get_ops_series, WINDOWS, DEFAULT_WINDOW


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

        return render(request, 'admin_dashboard/ops/dashboard.html', {
            'latest': latest,
            'chart_data': series,
            'incidents': incidents,
            'window': window,
            'window_options': [
                {'key': k, 'label': v['label']} for k, v in WINDOWS.items()
            ],
        })
