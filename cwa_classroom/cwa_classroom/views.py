"""
Project-level views (health check, version info, etc.)
"""

import datetime
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.core.cache import cache
from django.http import JsonResponse, HttpResponseRedirect
from django.middleware.csrf import REASON_NO_CSRF_COOKIE
from django.shortcuts import render
from django.urls import reverse, NoReverseMatch
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


def _utc_now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _check_database():
    """Round-trips a trivial query against the default connection."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        return True, None
    except Exception as exc:  # surface the failure, never swallow it
        return False, str(exc)


def _check_migrations():
    """Reports whether any migration is unapplied (schema drift)."""
    try:
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        pending = executor.migration_plan(targets)
        if pending:
            names = [f"{m.app_label}.{m.name}" for m, _backwards in pending]
            return False, f"{len(names)} unapplied: {', '.join(names[:10])}"
        return True, None
    except Exception as exc:
        return False, str(exc)


def _check_cache():
    """Writes and reads back a sentinel via the configured cache backend.

    Only meaningful when Redis is configured (REDIS_URL set); with the default
    local-memory cache this still validates the cache framework is wired up.
    """
    try:
        cache.set("healthcheck", "ok", timeout=10)
        return cache.get("healthcheck") == "ok", None
    except Exception as exc:
        return False, str(exc)


def health_check(request):
    """
    GET /api/health/         — shallow liveness + version (always 200 OK)
    GET /api/health/?deep=1  — also probes DB, migrations, and cache

    Shallow response (200 OK):
    {
        "status":   "ok",
        "version":  "1.5.0",
        "date":     "2026-06-01",
        "api":      "v1",
        "timestamp": "2026-06-01T12:00:00.000Z"
    }

    Deep response adds a "checks" object. If any check fails the overall
    "status" becomes "degraded" and the response code is 503 — so deploy
    scripts and uptime monitors can tell "the process is up" apart from
    "the app actually works".
    """
    body = {
        "status":    "ok",
        "version":   getattr(settings, "APP_VERSION",      "1.0.0"),
        "date":      getattr(settings, "APP_VERSION_DATE", ""),
        "api":       "v1",
        "timestamp": _utc_now_iso(),
    }

    deep = request.GET.get("deep") in ("1", "true", "yes")
    if not deep:
        return JsonResponse(body)

    checks = {}
    probes = [
        ("database",   _check_database),
        ("migrations", _check_migrations),
        ("cache",      _check_cache),
    ]
    all_ok = True
    for name, probe in probes:
        ok, detail = probe()
        checks[name] = {"ok": ok}
        if detail:
            checks[name]["detail"] = detail
        all_ok = all_ok and ok

    body["checks"] = checks
    if not all_ok:
        body["status"] = "degraded"
        return JsonResponse(body, status=503)

    return JsonResponse(body)


def _auth_urls():
    """(login_url, logout_url) — falls back to settings when a subdomain
    urlconf doesn't route the accounts app."""
    try:
        return reverse('login'), reverse('logout')
    except NoReverseMatch:
        return settings.LOGIN_URL, None


def csrf_failure(request, reason='', template_name='403_csrf.html'):
    """CSRF_FAILURE_VIEW — let a stale sign-in be retried instead of dead-ending.

    Signing in rotates the CSRF secret, so every form rendered *before* that
    login — a second tab, a page the back button restored, anything the browser
    kept — still carries a token the server no longer accepts. Logging out of
    one account and into another from such a page used to land on Django's bare
    "CSRF verification failed. Request aborted." page with no way forward
    (CPP-36).

    For the auth forms that means bouncing back to a freshly-tokened login page
    that explains what happened. Everything else keeps its 403 — the point is a
    branded page with a way out, not a hidden failure — and a blocked cookie
    (as opposed to a stale token) is always reported rather than retried, since
    a retry would fail identically.
    """
    logger.warning(
        'CSRF failure on %s %s (reason=%s, referer=%s)',
        request.method, request.path, reason, request.META.get('HTTP_REFERER', ''),
    )

    login_url, logout_url = _auth_urls()
    cookies_blocked = reason == REASON_NO_CSRF_COOKIE

    if not cookies_blocked and request.path in (login_url, logout_url):
        params = {'expired': '1'}
        next_url = request.POST.get('next') or request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            params['next'] = next_url
        return HttpResponseRedirect(f'{login_url}?{urlencode(params)}')

    return render(
        request,
        template_name,
        {'reason': reason, 'cookies_blocked': cookies_blocked, 'login_url': login_url},
        status=403,
    )
