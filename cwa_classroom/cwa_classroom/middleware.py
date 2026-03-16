"""
Subdomain routing middleware for CWA Classroom.

Maps subdomains to dedicated URL configurations so that each subject app
can eventually be served from its own subdomain (e.g. maths.wizardslearninghub.co.nz).

For local development, Chrome and Firefox resolve *.localhost to 127.0.0.1
natively, so no /etc/hosts editing is needed:
  - maths.localhost:8000     → maths URLs
  - coding.localhost:8000    → coding URLs
  - music.localhost:8000     → music URLs
  - science.localhost:8000   → science URLs
  - localhost:8000           → main URLs (default)

In production, add ALLOWED_HOSTS entries and set BASE_DOMAIN in the environment.
"""

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

# Map subdomain slug → URL conf module path.
# Add entries here as new subject apps are created.
SUBDOMAIN_URLCONFS = {
    'maths':   'cwa_classroom.urls_maths',
    'coding':  'cwa_classroom.urls_coding',
    'music':   'cwa_classroom.urls_music',
    'science': 'cwa_classroom.urls_science',
}


class SubdomainURLRoutingMiddleware:
    """
    Middleware that sets request.urlconf based on the subdomain of the request host.

    Falls back to ROOT_URLCONF (the default urls.py) when no subdomain matches,
    which means the main hub continues to work at the apex domain / localhost.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().lower().split(':')[0]   # strip port
        subdomain = self._get_subdomain(host)

        if subdomain and subdomain in SUBDOMAIN_URLCONFS:
            request.urlconf = SUBDOMAIN_URLCONFS[subdomain]

        return self.get_response(request)

    @staticmethod
    def _get_subdomain(host):
        """
        Extract the leftmost label of the hostname as the subdomain.
        Returns None when there is no meaningful subdomain
        (bare 'localhost', an IP address, or the apex domain itself).
        """
        # Bare IP — no subdomain
        if host.replace('.', '').isdigit():
            return None

        parts = host.split('.')

        # Single label (e.g. "localhost") — no subdomain
        if len(parts) < 2:
            return None

        # Two labels that look like an apex domain (e.g. "example.com") — no subdomain
        # We treat *.localhost as subdomains of "localhost"
        if parts[-1] == 'localhost':
            if len(parts) == 1:
                return None
            return parts[0]   # e.g. "maths" from "maths.localhost"

        # Production: e.g. maths.wizardslearninghub.co.nz
        # Anything with 3+ parts has a subdomain in the first label
        if len(parts) >= 3:
            return parts[0]

        return None


class MathsRoomRedirectMiddleware:
    """
    Permanently redirect mathsroom.wizardslearninghub.co.nz → /maths/

    Must be registered BEFORE SubdomainURLRoutingMiddleware in MIDDLEWARE so
    the redirect fires before any urlconf switching happens.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().lower().split(':')[0]
        if host == 'mathsroom.wizardslearninghub.co.nz':
            return redirect(
                'https://www.wizardslearninghub.co.nz/maths/',
                permanent=True,  # 301 — browsers and search engines cache this
            )
        return self.get_response(request)


class TrialExpiryMiddleware:
    """
    For individual students with an expired trial:
    - Auto-expire the subscription status in the database
    - Redirect all requests to the trial-expired page (keeps user logged in
      so they can access billing/checkout to pay)
    - Once payment is received and subscription status becomes 'active',
      the user gets full access again
    """

    ALLOWED_PATHS = (
        '/accounts/trial-expired/',
        '/accounts/logout/',
        '/billing/',
        '/stripe/',
        '/admin/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.is_individual_student:
            try:
                sub = request.user.subscription
            except Exception:
                sub = None

            if sub and self._is_trial_expired(sub):
                if sub.status != sub.STATUS_EXPIRED:
                    sub.status = sub.STATUS_EXPIRED
                    sub.save(update_fields=['status'])

                if not self._is_allowed_path(request.path):
                    return redirect('trial_expired')

        return self.get_response(request)

    @staticmethod
    def _is_trial_expired(sub):
        if sub.status == sub.STATUS_ACTIVE:
            return False
        if sub.status == sub.STATUS_EXPIRED:
            return True
        if sub.status == sub.STATUS_TRIALING and sub.trial_end:
            return timezone.now() > sub.trial_end
        return False

    def _is_allowed_path(self, path):
        return any(path.startswith(p) for p in self.ALLOWED_PATHS)
