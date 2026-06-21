"""Background task for the sprint burndown sync.

Thin RQ entry point — the config-gated Jira logic lives in
``sprints.services``. Mirrors ``feedback.tasks``.
"""
import logging

from . import services

logger = logging.getLogger(__name__)


def sync_sprint_burndown():
    """Record today's snapshot for the board's active sprint.

    Safe to enqueue/run repeatedly: ``services.sync_active_sprint`` is
    config-gated and upserts today's snapshot.
    """
    snapshot = services.sync_active_sprint()
    return {
        'sprint_id': snapshot.sprint_id if snapshot else None,
        'snapshot_date': snapshot.snapshot_date.isoformat() if snapshot else None,
    }
