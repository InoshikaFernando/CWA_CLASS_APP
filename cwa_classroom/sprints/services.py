"""Jira Agile integration for the sprint burndown.

Pulls the active sprint and its issues from Jira's Agile REST API
(``/rest/agile/1.0/``) and records a daily :class:`SprintSnapshot` of story
points remaining. Like ``feedback.services`` everything here is config-gated:
when the Jira env (or ``JIRA_BOARD_ID``) is unset the helpers log and return
``None``/empty rather than raising, so dev/test/local keep working untouched.

No silent failures: every non-2xx / exception path is logged.
"""
import logging

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Bound every outbound call so a hung Jira endpoint can't pin an RQ worker /
# cron run for its full timeout.
_HTTP_TIMEOUT = 15

# Issue statuses Jira groups under the "Done" status category. An issue counts
# as burned-down once it reaches this category.
_DONE_CATEGORY = 'done'


def _jira_config():
    """Return (base_url, auth, board_id, points_field) or None if unconfigured."""
    base_url = (settings.JIRA_BASE_URL or '').rstrip('/')
    email = settings.JIRA_USER_EMAIL
    token = settings.JIRA_API_TOKEN
    board_id = getattr(settings, 'JIRA_BOARD_ID', '')
    points_field = getattr(settings, 'JIRA_STORY_POINTS_FIELD', '') or 'customfield_10016'

    if not (base_url and email and token and board_id):
        logger.warning(
            'Jira burndown not configured (need JIRA_BASE_URL/JIRA_USER_EMAIL/'
            'JIRA_API_TOKEN/JIRA_BOARD_ID); skipping sync.'
        )
        return None
    return base_url, (email, token), board_id, points_field


def _get(base_url, path, auth, params=None):
    """GET ``{base_url}{path}`` and return parsed JSON, or None on any failure."""
    try:
        resp = requests.get(
            f'{base_url}{path}', auth=auth, params=params, timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error('Jira GET %s failed: %s', path, exc)
        return None

    if not (200 <= resp.status_code < 300):
        logger.error('Jira GET %s returned %s: %s', path, resp.status_code, resp.text)
        return None

    try:
        return resp.json()
    except ValueError as exc:
        logger.error('Jira GET %s returned non-JSON: %s (%s)', path, resp.text, exc)
        return None


def get_active_sprint(base_url, auth, board_id):
    """Return Jira's active sprint dict for ``board_id``, or None.

    If a board runs more than one active sprint we take the first; the
    burndown surface tracks a single sprint at a time.
    """
    data = _get(
        base_url, f'/rest/agile/1.0/board/{board_id}/sprint', auth,
        params={'state': 'active'},
    )
    if not data:
        return None
    values = data.get('values') or []
    if not values:
        logger.info('Jira board %s has no active sprint.', board_id)
        return None
    return values[0]


def iter_sprint_issues(base_url, auth, sprint_id, points_field):
    """Yield (story_points, is_done) for every issue in the sprint.

    Pages through ``/sprint/{id}/issue`` 50 at a time. Issues with no estimate
    contribute 0 points (Jira returns ``None`` for an unestimated field).
    """
    start_at = 0
    page_size = 50
    while True:
        data = _get(
            base_url, f'/rest/agile/1.0/sprint/{sprint_id}/issue', auth,
            params={
                'startAt': start_at,
                'maxResults': page_size,
                'fields': f'{points_field},status',
            },
        )
        if not data:
            return
        issues = data.get('issues') or []
        for issue in issues:
            fields = issue.get('fields') or {}
            points = fields.get(points_field) or 0
            try:
                points = float(points)
            except (TypeError, ValueError):
                points = 0.0
            category = (
                (fields.get('status') or {})
                .get('statusCategory', {})
                .get('key', '')
            )
            yield points, category == _DONE_CATEGORY

        start_at += len(issues)
        if start_at >= (data.get('total') or 0) or not issues:
            return


def _parse_date(value):
    """Parse a Jira ISO datetime (e.g. '2026-06-01T09:00:00.000Z') to a date."""
    if not value:
        return None
    try:
        return timezone.datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except (ValueError, AttributeError):
        return None


def sync_active_sprint():
    """Sync the board's active sprint and record today's snapshot.

    Returns the created/updated :class:`SprintSnapshot`, or None when Jira is
    unconfigured or has no active sprint. Idempotent per day: re-running
    upserts today's snapshot rather than duplicating it.
    """
    from .models import Sprint, SprintSnapshot

    config = _jira_config()
    if not config:
        return None
    base_url, auth, board_id, points_field = config

    jira_sprint = get_active_sprint(base_url, auth, board_id)
    if not jira_sprint:
        return None

    sprint, created = Sprint.objects.update_or_create(
        jira_sprint_id=jira_sprint['id'],
        defaults={
            'name': jira_sprint.get('name', f"Sprint {jira_sprint['id']}"),
            'state': jira_sprint.get('state', Sprint.STATE_ACTIVE),
            'start_date': _parse_date(jira_sprint.get('startDate')),
            'end_date': _parse_date(jira_sprint.get('endDate')),
            'goal': jira_sprint.get('goal') or '',
        },
    )

    remaining = 0.0
    completed = 0.0
    for points, is_done in iter_sprint_issues(base_url, auth, sprint.jira_sprint_id, points_field):
        if is_done:
            completed += points
        else:
            remaining += points
    total = remaining + completed

    # Capture the committed baseline once, on the first snapshot of the sprint,
    # so later scope changes don't shift the ideal line.
    if created or not sprint.committed_points:
        sprint.committed_points = total
        sprint.save(update_fields=['committed_points', 'updated_at'])

    snapshot, _ = SprintSnapshot.objects.update_or_create(
        sprint=sprint,
        snapshot_date=timezone.localdate(),
        defaults={
            'remaining_points': remaining,
            'completed_points': completed,
            'total_points': total,
        },
    )
    logger.info(
        'Sprint burndown synced: %s — %.1f remaining / %.1f total on %s',
        sprint.name, remaining, total, snapshot.snapshot_date,
    )
    return snapshot
