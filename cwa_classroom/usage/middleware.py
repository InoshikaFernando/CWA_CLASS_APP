"""Usage tracking middleware.

Records one PageHit per real HTML page view (and per error response on a
page route) so the superuser Usage Analytics dashboard has data to chart.

Deliberately narrow: static files, media, /admin/, Stripe webhooks, health
checks and AJAX/HTMX/JSON requests are skipped so the table stays lean and
"most visited page" stays meaningful. Tracking is wrapped in try/except so a
logging failure can never break a real request.

Register LAST in MIDDLEWARE so the status code seen here is the final one.
"""
import logging

logger = logging.getLogger(__name__)

# Path prefixes that never count as a "page view".
EXCLUDED_PREFIXES = (
    '/static/',
    '/media/',
    '/admin/',
    '/admin-dashboard/',  # superuser admin/analytics pages (incl. this dashboard)
    '/stripe/',        # Stripe webhooks / redirects
    '/__',             # /__debug__/, /__reload__/ etc.
    '/favicon',
    '/sw.js',
    '/health',
    '/billing/portal',  # server-side redirect to Stripe, not a page
)


class UsageTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if self._should_track(request, response):
                self._record(request, response)
        except Exception:  # never let tracking break a response
            logger.exception('UsageTrackingMiddleware failed to record page hit')
        return response

    def _should_track(self, request, response):
        if request.method != 'GET':
            return False

        path = request.path
        if path.startswith(EXCLUDED_PREFIXES):
            return False

        # Skip partial / API style requests — not real page views.
        if getattr(request, 'htmx', False):
            return False
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return False
        accept = request.headers.get('accept', '')
        if 'text/html' not in accept and 'application/json' in accept:
            return False

        status = response.status_code
        content_type = response.get('Content-Type', '') or ''
        # Count only successful HTML pages as page views. 3xx redirects also
        # carry text/html but aren't a page the user looked at, and counting
        # them double-counts redirect loops (expired trial, login-required).
        # Still record every >=400 (incl. JSON 500s on page URLs) so the
        # 4xx/5xx chart is complete.
        is_page_view = content_type.startswith('text/html') and 200 <= status < 300
        return is_page_view or status >= 400

    def _record(self, request, response):
        from .models import PageHit

        user = getattr(request, 'user', None)
        if user is not None and not user.is_authenticated:
            user = None

        session_key = ''
        session = getattr(request, 'session', None)
        if session is not None:
            session_key = session.session_key or ''

        PageHit.objects.create(
            path=request.path[:255],
            method=request.method,
            status_code=response.status_code,
            user=user,
            session_key=session_key,
        )
