"""
Project-level views (health check, version info, etc.)
"""

import datetime
from django.conf import settings
from django.http import JsonResponse


def health_check(request):
    """
    GET /api/health/

    Returns app version, status, and server UTC timestamp.
    Used for deployment checks, uptime monitoring, and client version negotiation.

    Response (200 OK):
    {
        "status":   "ok",
        "version":  "1.0.0",
        "date":     "2026-04-07",
        "api":      "v1",
        "timestamp": "2026-04-07T12:00:00.000Z"
    }
    """
    return JsonResponse({
        "status":    "ok",
        "version":   getattr(settings, "APP_VERSION",      "1.0.0"),
        "date":      getattr(settings, "APP_VERSION_DATE", ""),
        "api":       "v1",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    })
