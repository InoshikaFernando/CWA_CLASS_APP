"""Shared Jira REST client.

Thin, config-gated wrapper used by both the feedback bug-filing integration
(``feedback.services``) and the sprint burndown sync (``sprints.services``).
Centralises the base-URL / auth / timeout / error-logging contract so a change
to how we talk to Jira (auth scheme, retries, proxy) lands in exactly one place
rather than drifting between consumers.

Never raises into callers: every failure path logs and returns ``None``.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Bound every outbound call so a hung Jira endpoint can't pin a worker / cron
# run for its full job timeout.
HTTP_TIMEOUT = 15


def base_config():
    """Return ``(base_url, (email, token))`` or ``None`` when Jira is unset.

    ``base_url`` is normalised (trailing slash stripped). Returns ``None`` —
    rather than raising — when any of the three core credentials is missing, so
    callers can treat "no Jira configured" as a no-op.
    """
    base_url = (settings.JIRA_BASE_URL or '').rstrip('/')
    email = settings.JIRA_USER_EMAIL
    token = settings.JIRA_API_TOKEN
    if not (base_url and email and token):
        return None
    return base_url, (email, token)


def request(method, path, *, json=None, params=None):
    """Call Jira ``method {base_url}{path}`` and return parsed JSON, or ``None``.

    Returns ``None`` (and logs) when Jira is unconfigured, the request raises,
    the response is non-2xx, or the body isn't JSON. ``path`` is appended to the
    configured base URL (e.g. ``/rest/api/3/issue``).
    """
    config = base_config()
    if config is None:
        logger.warning('Jira not configured; skipping %s %s', method, path)
        return None
    base_url, auth = config

    try:
        resp = requests.request(
            method, f'{base_url}{path}',
            json=json, params=params, auth=auth, timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error('Jira %s %s failed: %s', method, path, exc)
        return None

    if not (200 <= resp.status_code < 300):
        logger.error('Jira %s %s returned %s: %s', method, path, resp.status_code, resp.text)
        return None

    try:
        return resp.json()
    except ValueError as exc:
        logger.error('Jira %s %s returned non-JSON body: %s (%s)', method, path, resp.text, exc)
        return None
