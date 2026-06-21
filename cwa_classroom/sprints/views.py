"""Burndown chart surface.

Superuser-only, matching the rest of the platform super-admin area
(admin-dashboard/billing/...). Renders the active sprint's burndown from
stored snapshots; the daily sync (management command / RQ task) keeps those
snapshots fresh.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from .burndown import build_burndown_series
from .models import Sprint


class SuperuserRequiredMixin(LoginRequiredMixin):
    """Restrict access to superusers only. Redirects with an error if not.

    Mirrors billing.views_admin.SuperuserRequiredMixin so the burndown sits in
    the same super-admin surface as the billing admin pages.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_superuser:
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('subjects_hub')
        return super().dispatch(request, *args, **kwargs)


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
