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

        # Successful HTML page view (2xx). 3xx redirects also carry text/html
        # but aren't a page the user looked at, so they're excluded.
        if content_type.startswith('text/html') and 200 <= status < 300:
            return True

        # Server errors (5xx) are always real app failures — always record.
        if status >= 500:
            return True

        # Client errors (4xx): record ONLY when the URL matched a real route
        # (a genuine in-app "not found", e.g. /homework/13/take/ for a missing
        # object). A 4xx on a path that matched NO url pattern
        # (request.resolver_match is None) is a bot/scanner/asset probe —
        # /wp-login.php, *.php, /.env, apple-touch-icon, random paths — the
        # dominant source of 404 noise. Don't record those at all.
        if status >= 400:
            return getattr(request, 'resolver_match', None) is not None

        return False

    def _record(self, request, response):
        from .models import PageHit

        user = getattr(request, 'user', None)
        if user is not None and not user.is_authenticated:
            user = None

        session_key = ''
        session = getattr(request, 'session', None)
        if session is not None:
            session_key = session.session_key or ''

        # Never let a fingerprinting edge case drop the whole row (the page
        # view / error still matters even without a guest key).
        try:
            client_key = self._client_key(request)
        except Exception:
            client_key = ''

        PageHit.objects.create(
            path=request.path[:255],
            method=request.method,
            status_code=response.status_code,
            user=user,
            session_key=session_key,
            client_key=client_key,
        )

    @staticmethod
    def _client_key(request):
        """Stable, non-reversible per-visitor key from IP + user agent.

        Used to count distinct guests (anonymous visitors) without relying on
        a saved session. Salted with SECRET_KEY so the stored value can't be
        reversed to an IP.
        """
        import hashlib
        from django.conf import settings
        from audit.services import get_client_ip

        ip = get_client_ip(request) or ''
        ua = request.headers.get('user-agent', '')
        if not ip and not ua:
            return ''
        raw = f'{settings.SECRET_KEY}:{ip}:{ua}'.encode('utf-8', 'ignore')
        return hashlib.sha256(raw).hexdigest()[:32]
