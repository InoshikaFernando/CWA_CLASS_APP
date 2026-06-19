"""Outbound integrations for the feedback app (CPP-321).

Files a Jira CPP *Bug* issue for every bug-category feedback item and announces
it on Discord. Everything here is config-gated: when the Jira / Discord env is
unset the helpers log and no-op rather than raising, so a missing integration
never breaks the user's feedback submission.

No silent failures: every non-2xx / exception path is logged (warning when the
integration is simply unconfigured, error when a configured call fails).
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Bound every outbound HTTP call so a hung Jira/Discord endpoint can't pin an
# RQ worker for the full job timeout.
_HTTP_TIMEOUT = 10


def _adf_description(text):
    """Wrap plain text in a minimal Atlassian Document Format (ADF) doc.

    Jira's REST v3 ``description`` field must be ADF, not a string. A single
    paragraph node carrying the text is the simplest valid document.
    """
    return {
        'type': 'doc',
        'version': 1,
        'content': [
            {
                'type': 'paragraph',
                'content': [
                    {'type': 'text', 'text': text or ''},
                ],
            },
        ],
    }


def create_jira_bug(*, summary, description, labels=None):
    """Create a Jira Bug issue and return its key (e.g. ``"CPP-123"``).

    Returns ``None`` (and logs) when the Jira env is unconfigured or the API
    responds non-2xx. Never raises into the caller — bug filing must not be able
    to fail a feedback submission or crash the worker.
    """
    base_url = (settings.JIRA_BASE_URL or '').rstrip('/')
    email = settings.JIRA_USER_EMAIL
    token = settings.JIRA_API_TOKEN
    project_key = settings.JIRA_PROJECT_KEY

    if not (base_url and email and token):
        logger.warning(
            'Jira not configured (JIRA_BASE_URL/JIRA_USER_EMAIL/'
            'JIRA_API_TOKEN); skipping bug creation for: %s', summary,
        )
        return None

    payload = {
        'fields': {
            'project': {'key': project_key},
            'summary': summary,
            'description': _adf_description(description),
            'issuetype': {'name': 'Bug'},
            'labels': labels or [],
        }
    }

    try:
        resp = requests.post(
            f'{base_url}/rest/api/3/issue',
            json=payload,
            auth=(email, token),
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error('Jira issue creation request failed: %s', exc)
        return None

    if not (200 <= resp.status_code < 300):
        logger.error(
            'Jira issue creation returned %s: %s',
            resp.status_code, resp.text,
        )
        return None

    try:
        key = resp.json().get('key')
    except ValueError as exc:
        logger.error('Jira returned non-JSON success body: %s (%s)', resp.text, exc)
        return None

    if not key:
        logger.error('Jira success response had no issue key: %s', resp.text)
        return None

    logger.info('Created Jira bug %s for: %s', key, summary)
    return key


def post_discord(content):
    """Post ``content`` to the configured Discord webhook. Returns success.

    No-ops (returns ``False``) when no webhook is configured. Logs on failure;
    never raises.
    """
    webhook = settings.FEEDBACK_DISCORD_WEBHOOK
    if not webhook:
        return False

    try:
        resp = requests.post(
            webhook, json={'content': content}, timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error('Discord webhook post failed: %s', exc)
        return False

    if not (200 <= resp.status_code < 300):
        logger.error(
            'Discord webhook returned %s: %s', resp.status_code, resp.text,
        )
        return False

    return True


def report_feedback_bug(feedback):
    """File a Jira bug for ``feedback`` and announce it on Discord.

    Idempotent: a feedback item that already carries a ``jira_key`` is skipped,
    so a re-run (RQ retry, duplicate enqueue) won't create duplicate issues.
    """
    if feedback.jira_key:
        logger.info(
            'Feedback %s already has Jira key %s; skipping.',
            feedback.pk, feedback.jira_key,
        )
        return

    reporter = getattr(feedback.submitted_by, 'email', '') or 'unknown'
    title = feedback.title or (feedback.description or '')[:80]

    summary = f'[Feedback] {title}'
    description = (
        f'{feedback.description}\n\n'
        f'Reporter: {reporter}\n'
        f'Role: {feedback.role or "(unknown)"}\n'
        f'School: {feedback.school or "(none)"}\n'
        f'Page: {feedback.page_url or "(none)"}'
    )

    key = create_jira_bug(
        summary=summary,
        description=description,
        labels=['feedback', 'user-reported'],
    )

    if key:
        feedback.jira_key = key
        feedback.save(update_fields=['jira_key', 'updated_at'])
        base_url = (settings.JIRA_BASE_URL or '').rstrip('/')
        link = f'{base_url}/browse/{key}' if base_url else key
    else:
        link = '(Jira not configured)'

    post_discord(
        f'\U0001f41e New bug from feedback: {title} — {link} — by {reporter}'
    )
