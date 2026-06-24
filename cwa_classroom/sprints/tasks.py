"""Background task for the sprint burndown sync.

Thin RQ entry point — the config-gated Jira logic lives in
``sprints.services``. Mirrors ``feedback.tasks``.
"""
import logging

from . import services

logger = logging.getLogger(__name__)


def sync_sprint_burndown():
    """Record today's whole-project snapshot (and the active-sprint one).

    Safe to enqueue/run repeatedly: both services are config-gated and upsert
    today's snapshot. The project snapshot drives the burndown page; the sprint
    snapshot is kept for per-sprint history.
    """
    project = services.sync_project_burndown()
    sprint = services.sync_active_sprint()
    return {
        'project_snapshot_date': project.snapshot_date.isoformat() if project else None,
        'sprint_id': sprint.sprint_id if sprint else None,
    }
