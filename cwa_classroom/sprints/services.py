"""Jira Agile integration for the sprint burndown.

Pulls the active sprint and its issues from Jira's Agile REST API
(``/rest/agile/1.0/``) via the shared ``cwa_classroom.jira_client`` and records
a daily :class:`SprintSnapshot` of story points remaining. Config-gated: when
the Jira env (or ``JIRA_BOARD_ID``) is unset the helpers log and return
``None``, so dev/test/local keep working untouched.

No silent failures: every non-2xx / exception path is logged, and a *partial*
fetch (a mid-pagination error) aborts the sync rather than recording a
too-low snapshot.
"""
import logging

from django.conf import settings
from django.utils import timezone

from cwa_classroom import jira_client

logger = logging.getLogger(__name__)

# Issue statuses Jira groups under the "Done" status category. An issue counts
# as burned-down once it reaches this category.
_DONE_CATEGORY = 'done'

_PAGE_SIZE = 50


def _burndown_config():
    """Return (board_id, points_field) or None when burndown is unconfigured.

    Requires the base Jira credentials (delegated to the shared client) *and* a
    board id to read the active sprint from.
    """
    if jira_client.base_config() is None:
        logger.warning(
            'Jira burndown not configured (JIRA_BASE_URL/JIRA_USER_EMAIL/'
            'JIRA_API_TOKEN unset); skipping sync.'
        )
        return None

    board_id = getattr(settings, 'JIRA_BOARD_ID', '')
    if not board_id:
        logger.warning('Jira burndown not configured (JIRA_BOARD_ID unset); skipping sync.')
        return None

    points_field = getattr(settings, 'JIRA_STORY_POINTS_FIELD', '') or 'customfield_10016'
    return board_id, points_field


def get_active_sprint(board_id):
    """Return Jira's active sprint dict for ``board_id``, or None.

    If a board runs more than one active sprint we take the first; the burndown
    surface tracks a single sprint at a time.
    """
    data = jira_client.request(
        'GET', f'/rest/agile/1.0/board/{board_id}/sprint', params={'state': 'active'},
    )
    if not data:
        return None
    values = data.get('values') or []
    if not values:
        logger.info('Jira board %s has no active sprint.', board_id)
        return None
    return values[0]


def fetch_sprint_points(sprint_id, points_field):
    """Return ``(remaining, completed, issue_count)`` for the sprint, or None.

    Sums story points across every issue, paging 50 at a time. Returns ``None``
    if any page fetch fails — the caller then skips writing a snapshot rather
    than persisting a silently-truncated (too-low) total. Pages until a short
    page is returned; we don't trust the response's ``total`` field (it can be
    absent), so pagination terminates on ``len(page) < page_size`` instead.
    """
    start_at = 0
    remaining = 0.0
    completed = 0.0
    issue_count = 0

    while True:
        data = jira_client.request(
            'GET', f'/rest/agile/1.0/sprint/{sprint_id}/issue',
            params={
                'startAt': start_at,
                'maxResults': _PAGE_SIZE,
                'fields': f'{points_field},status',
            },
        )
        if data is None:
            logger.error(
                'Aborting burndown sync: issue page fetch failed at startAt=%s '
                'for sprint %s (snapshot not recorded).', start_at, sprint_id,
            )
            return None

        issues = data.get('issues') or []
        for issue in issues:
            fields = issue.get('fields') or {}
            raw = fields.get(points_field)
            try:
                points = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                points = 0.0
            category = (
                (fields.get('status') or {})
                .get('statusCategory', {})
                .get('key', '')
            )
            if category == _DONE_CATEGORY:
                completed += points
            else:
                remaining += points

        issue_count += len(issues)
        start_at += len(issues)
        if len(issues) < _PAGE_SIZE:
            break

    return remaining, completed, issue_count


def _parse_date(value):
    """Parse a Jira ISO datetime to a project-local date.

    Jira returns UTC timestamps (e.g. '2026-06-12T22:00:00.000Z'). We convert to
    the project timezone before taking ``.date()`` so sprint dates line up with
    the locally-dated snapshots (``timezone.localdate()``) rather than drifting a
    day in non-UTC deployments.
    """
    if not value:
        return None
    try:
        dt = timezone.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    return timezone.localtime(dt).date()


def sync_active_sprint():
    """Sync the board's active sprint and record today's snapshot.

    Returns the created/updated :class:`SprintSnapshot`, or None when Jira is
    unconfigured, has no active sprint, or an issue page failed to fetch.
    Idempotent per day: re-running upserts today's snapshot.
    """
    from .models import Sprint, SprintSnapshot

    config = _burndown_config()
    if not config:
        return None
    board_id, points_field = config

    jira_sprint = get_active_sprint(board_id)
    if not jira_sprint:
        return None

    points = fetch_sprint_points(jira_sprint['id'], points_field)
    if points is None:
        return None  # partial/failed fetch — don't persist a wrong snapshot
    remaining, completed, issue_count = points
    total = remaining + completed

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

    # Capture the committed baseline exactly once, on the first sync that sees a
    # non-zero total, then lock it via the explicit flag so later scope changes
    # don't move the ideal line. (A truthy check on committed_points would treat
    # a legitimate 0 as "unset" and re-capture forever.)
    if not sprint.baseline_captured and total > 0:
        sprint.committed_points = total
        sprint.baseline_captured = True
        sprint.save(update_fields=['committed_points', 'baseline_captured', 'updated_at'])

    # A sprint with issues but zero story points almost always means
    # JIRA_STORY_POINTS_FIELD doesn't match this Jira instance — surface it
    # rather than rendering a silent flat-zero burndown.
    if issue_count > 0 and total == 0:
        logger.warning(
            'Sprint "%s" has %d issue(s) but 0 story points — check '
            'JIRA_STORY_POINTS_FIELD (%s) matches your Jira instance.',
            sprint.name, issue_count, points_field,
        )

    snapshot, _ = SprintSnapshot.objects.update_or_create(
        sprint=sprint,
        snapshot_date=timezone.localdate(),
        defaults={
            'remaining_points': remaining,
            'completed_points': completed,
        },
    )
    logger.info(
        'Sprint burndown synced: %s — %.1f remaining / %.1f total on %s',
        sprint.name, remaining, total, snapshot.snapshot_date,
    )
    return snapshot
