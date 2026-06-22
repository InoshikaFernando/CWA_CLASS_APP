"""Burndown chart surface.

Superuser-only, reusing billing.views_admin.SuperuserRequiredMixin so the
burndown sits behind the same gate as the rest of the platform super-admin area
(admin-dashboard/billing/...). Renders the active sprint's burndown from stored
snapshots; the daily sync (management command / RQ task) keeps them fresh.
"""
from django.shortcuts import render
from django.views import View

from billing.views_admin import SuperuserRequiredMixin

from .burndown import build_burndown_series
from .models import Sprint


class BurndownChartView(SuperuserRequiredMixin, View):
    """Show the burndown for the most recent active sprint (or latest sprint).

    Defaults to the active sprint; falls back to the most recently started
    sprint so a closed sprint can still be reviewed.
    """

    def get(self, request):
        sprint = (
            Sprint.objects.filter(state=Sprint.STATE_ACTIVE).first()
            or Sprint.objects.first()
        )
        series = build_burndown_series(sprint) if sprint else None
        context = {
            'sprint': sprint,
            'series': series,
        }
        return render(request, 'sprints/burndown.html', context)
