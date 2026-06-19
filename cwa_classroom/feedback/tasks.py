"""Background tasks for the feedback app (CPP-321).

Mirrors worksheets.tasks — runs in an RQ worker process, loads the model from
the DB by id, and delegates to the service layer. Kept thin so the integration
logic (and its config-gating) all lives in ``feedback.services``.
"""
import logging

from . import services

logger = logging.getLogger(__name__)


def report_bug_to_jira(feedback_id):
    """File a Jira bug + Discord notice for a bug-category Feedback item.

    Loads the Feedback by id and hands off to ``services.report_feedback_bug``,
    which is config-gated and idempotent (skips items that already have a
    ``jira_key``).
    """
    from .models import Feedback

    feedback = Feedback.objects.get(pk=feedback_id)
    services.report_feedback_bug(feedback)
    return {'feedback_id': feedback_id, 'jira_key': feedback.jira_key}
