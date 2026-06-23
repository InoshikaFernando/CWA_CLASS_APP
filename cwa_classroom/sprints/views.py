"""Burndown chart surface.

Superuser-only, reusing billing.views_admin.SuperuserRequiredMixin so the
burndown sits behind the same gate as the rest of the platform super-admin area
(admin-dashboard/billing/...). Renders the *whole-project* burndown from stored
ProjectSnapshots; the scheduled sync (management command / RQ task) keeps them
fresh. (Per-sprint snapshots are still collected by the sync — see
services.sync_active_sprint — but the page shows the project as a whole.)
"""
from django.conf import settings
from django.shortcuts import render
from django.views import View

from billing.views_admin import SuperuserRequiredMixin

from .burndown import build_project_series
from .models import ProjectSnapshot


class BurndownChartView(SuperuserRequiredMixin, View):
    """Show the whole-project story-point burndown from stored snapshots."""

    def get(self, request):
        snapshots = list(ProjectSnapshot.objects.order_by('snapshot_date'))
        series = build_project_series(snapshots) if snapshots else None
        # "Last synced" = most recent upsert (updated_at, bumped on every run).
        last_synced = (
            max((s.updated_at for s in snapshots), default=None)
            if snapshots else None
        )
        context = {
            'series': series,
            'last_synced': last_synced,
            'project_key': settings.JIRA_PROJECT_KEY,
            'latest': snapshots[-1] if snapshots else None,
        }
        return render(request, 'sprints/burndown.html', context)
