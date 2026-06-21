"""Burndown chart surface.

Owner-only (reuses the feedback triage owner gate). Renders the active sprint's
burndown from stored snapshots; the daily sync (management command / RQ task)
keeps those snapshots fresh.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views import View

from feedback.owner import is_feedback_owner

from .burndown import build_burndown_series
from .models import Sprint


class OwnerRequiredMixin(LoginRequiredMixin):
    """Restrict a view to the platform feedback/product owner."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_feedback_owner(request.user):
            raise PermissionDenied("You don't have access to the sprint burndown.")
        return super().dispatch(request, *args, **kwargs)


class BurndownChartView(OwnerRequiredMixin, View):
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
