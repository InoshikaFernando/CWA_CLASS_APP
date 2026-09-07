"""Outbound integrations for the feedback app (CPP-321).

Files a Jira CPP *Bug* issue for every bug-category feedback item and announces
it on Discord. Everything here is config-gated: when the Jira / Discord env is
unset the helpers log and no-op rather than raising, so a missing integration
never breaks the user's feedback submission.

No silent failures: every non-2xx / exception path is logged (warning when the
integration is simply unconfigured, error when a configured call fails).
"""
import logging
import mimetypes
import os

import requests
from django.conf import settings

from cwa_classroom import jira_client

logger = logging.getLogger(__name__)

# Bound the Discord call so a hung webhook can't pin an RQ worker for the full
# job timeout. (Jira calls are bounded by jira_client.HTTP_TIMEOUT.)
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
    if jira_client.base_config() is None:
        logger.warning(
            'Jira not configured (JIRA_BASE_URL/JIRA_USER_EMAIL/'
            'JIRA_API_TOKEN); skipping bug creation for: %s', summary,
        )
        return None

    payload = {
        'fields': {
            'project': {'key': settings.JIRA_PROJECT_KEY},
            'summary': summary,
            'description': _adf_description(description),
            'issuetype': {'name': 'Bug'},
            'labels': labels or [],
        }
    }

    data = jira_client.request('POST', '/rest/api/3/issue', json=payload)
    if data is None:
        # jira_client already logged the failure cause.
        return None

    key = data.get('key')
    if not key:
        logger.error('Jira success response had no issue key: %s', data)
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

    # A report raised from a question card names the question (CPP-398). The
    # ticket that prompted this — "the answer in a quality answer was 23 or 23
    # pencils but why" against a topic quiz serving dozens of questions — could
    # not be traced to one without it, so the complaint was unactionable.
    report = feedback.question_reports.select_related('question').first()
    if report is not None and report.question_id:
        question = report.question
        description += (
            f'\nQuestion: #{question.id} — '
            f'{(question.question_text or "")[:200]}'
        )

    key = create_jira_bug(
        summary=summary,
        description=description,
        labels=['feedback', 'user-reported'],
    )

    if key:
        feedback.jira_key = key
        feedback.save(update_fields=['jira_key', 'updated_at'])
        attach_feedback_images(feedback, key)
        base_url = (settings.JIRA_BASE_URL or '').rstrip('/')
        link = f'{base_url}/browse/{key}' if base_url else key
    else:
        link = '(Jira not configured)'

    shots = feedback.images.count()
    suffix = f' ({shots} screenshot{"s" if shots != 1 else ""})' if shots else ''
    post_discord(
        f'\U0001f41e New bug from feedback: {title} — {link} — by {reporter}{suffix}'
    )


def attach_feedback_images(feedback, issue_key):
    """Push each of ``feedback``'s screenshots onto the Jira issue.

    Best-effort and isolated: a storage read or upload failure on one image is
    logged and skipped so it can't lose the others or crash the worker. The
    stored image already survives in our own media (Spaces), so a failed Jira
    push degrades traceability, not the record.
    """
    for img in feedback.images.all():
        try:
            with img.image.open('rb') as fh:
                content = fh.read()
            filename = os.path.basename(img.image.name) or f'screenshot-{img.pk}.png'
            content_type = mimetypes.guess_type(filename)[0] or 'image/png'
            jira_client.upload_attachment(
                issue_key, filename, content, content_type=content_type,
            )
        except Exception:
            logger.exception(
                'Could not attach feedback image %s to Jira %s', img.pk, issue_key,
            )
