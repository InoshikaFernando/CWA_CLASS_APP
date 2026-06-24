"""
Project-level views (health check, version info, etc.)
"""

import datetime

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.core.cache import cache
from django.http import JsonResponse


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
