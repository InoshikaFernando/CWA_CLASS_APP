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

import logging
import time

from django.conf import settings
from django.contrib.auth import logout
from django.db import connection
from django.shortcuts import redirect
from django.utils import timezone

_slow_query_log = logging.getLogger('slow_queries')

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
    Handles trial/subscription expiry for both individual students and institutes.

    Individual students:
    - Auto-expire subscription when trial ends
    - Redirect to trial-expired page (keep logged in for billing access)

    Institute users (HoI, HoD, teachers, accountants, school students):
    - Auto-expire school subscription when trial ends
    - Redirect to institute-trial-expired page
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
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Individual student trial/subscription expiry
        if request.user.is_individual_student:
            try:
                sub = request.user.subscription
            except Exception:
                sub = None

            # No subscription at all → treat as expired
            if not sub:
                if not self._is_allowed_path(request.path):
                    self._log_block(request, 'individual_no_subscription', 'none')
                    return redirect('trial_expired')
                return self.get_response(request)

            if self._is_trial_expired(sub):
                # Only auto-expire a genuinely-expired TRIAL. Preserve real
                # Stripe statuses (past_due / cancelled) so the payment wall
                # shows the correct "Payment Failed → Update card" message and
                # our status doesn't drift from Stripe.
                if sub.status == sub.STATUS_TRIALING:
                    sub.status = sub.STATUS_EXPIRED
                    sub.save(update_fields=['status'])

                if not self._is_allowed_path(request.path):
                    self._log_block(request, 'individual_subscription_expired', sub.status)
                    return redirect('trial_expired')

            return self.get_response(request)

        # Personal subscription enforcement for non-individual roles.
        # School students and parents who self-pay hold their OWN recurring
        # Subscription; a failed/lost card leaves it past_due. Without this check
        # the delinquent personal sub was ignored — only the school sub was
        # inspected below — so a self-paying student kept full access by riding
        # their school's active plan. A 100%-discount sub stays active (not
        # delinquent) and is never blocked here.
        personal_redirect = self._check_personal_subscription(request)
        if personal_redirect:
            return personal_redirect

        # Institute subscription expiry
        if self._is_institute_user(request.user):
            redirect_response = self._check_institute_subscription(request)
            if redirect_response:
                return redirect_response

        return self.get_response(request)

    def _check_institute_subscription(self, request):
        """
        Check if the institute user's school subscription has expired.
        For multi-school students: only block if ALL schools are expired.
        """
        from billing.entitlements import get_school_for_user, any_school_has_active_subscription
        from billing.models import SchoolSubscription

        school = get_school_for_user(request.user)
        if not school:
            return None

        try:
            sub = school.subscription
        except SchoolSubscription.DoesNotExist:
            return None

        if self._is_school_sub_expired(sub):
            # Only auto-expire a genuinely-expired TRIAL; preserve real Stripe
            # statuses (past_due / cancelled / suspended) so the wall message and
            # our records stay truthful.
            if sub.status == SchoolSubscription.STATUS_TRIALING:
                sub.status = SchoolSubscription.STATUS_EXPIRED
                sub.save(update_fields=['status'])

            # Multi-school: don't block if another school is still active
            if any_school_has_active_subscription(request.user):
                return None

            if not self._is_allowed_path(request.path):
                self._log_block(request, 'school_subscription_expired', sub.status)
                return redirect('institute_trial_expired')

        return None

    def _check_personal_subscription(self, request):
        """Block a self-paying user whose OWN recurring subscription is delinquent.

        Targets school students / parents who self-pay via a personal
        ``billing.Subscription`` (e.g. the per-student monthly plan). Individual
        students are handled by their dedicated branch above and never reach here.

        Scope is limited to the self-paying roles (STUDENT, PARENT) on purpose:
        staff (teachers/HoD/HoI/accountant) and superusers must NOT be locked out
        of running their school by a stale personal sub they may hold.

        Rules:
          - Not a self-paying role, or no personal subscription → None (they ride
            the school plan; the school-subscription check below still applies).
          - active / trialing (incl. an active 100%-discount free sub) → allowed.
          - past_due / expired / cancelled → redirect to the payment wall, unless
            already on an allowed billing path.
        """
        from accounts.models import Role
        from billing.models import Subscription

        user = request.user
        if not (user.has_role(Role.STUDENT) or user.has_role(Role.PARENT)):
            return None
        try:
            sub = user.subscription
        except Subscription.DoesNotExist:
            return None
        if sub.is_active_or_trialing:
            return None
        if not self._is_allowed_path(request.path):
            self._log_block(request, 'personal_subscription_delinquent', sub.status)
            return redirect('trial_expired')
        return None

    @staticmethod
    def _log_block(request, reason, sub_status=''):
        """Audit-log a subscription/trial block so every denial is provable
        (who, when, which page, why). log_event swallows its own errors, so this
        can never break the request."""
        from audit.services import log_event
        log_event(
            user=request.user, category='entitlement',
            action='subscription_blocked', result='blocked',
            detail={'reason': reason, 'sub_status': sub_status, 'path': request.path},
            request=request,
        )

    @staticmethod
    def _is_institute_user(user):
        """Check if user is associated with an institute (not an individual student)."""
        from accounts.models import Role
        institute_roles = (
            Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
            Role.HEAD_OF_DEPARTMENT, Role.ACCOUNTANT,
            Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
            Role.STUDENT,
        )
        return any(user.has_role(r) for r in institute_roles)

    @staticmethod
    def _is_trial_expired(sub):
        if sub.status == sub.STATUS_ACTIVE:
            return False
        if sub.status in (sub.STATUS_EXPIRED, sub.STATUS_CANCELLED, sub.STATUS_PAST_DUE):
            return True
        if sub.status == sub.STATUS_TRIALING and sub.trial_end:
            return timezone.now() > sub.trial_end
        return False

    @staticmethod
    def _is_school_sub_expired(sub):
        from billing.models import SchoolSubscription
        if sub.status == SchoolSubscription.STATUS_ACTIVE:
            return False
        if sub.status in (
            SchoolSubscription.STATUS_EXPIRED,
            SchoolSubscription.STATUS_CANCELLED,
            SchoolSubscription.STATUS_SUSPENDED,
            SchoolSubscription.STATUS_PAST_DUE,
        ):
            return True
        if sub.status == SchoolSubscription.STATUS_TRIALING and sub.trial_end:
            return timezone.now() > sub.trial_end
        return False

    def _is_allowed_path(self, path):
        return any(path.startswith(p) for p in self.ALLOWED_PATHS)


class AccountBlockMiddleware:
    """
    Block access for suspended/blocked accounts.

    - Checks if the user's account is blocked (temporary or permanent).
    - Auto-unblocks temporary blocks that have expired.
    - Checks if the user's school is suspended.
    - Forces logout and redirects to the blocked page.

    Must be placed AFTER AuthenticationMiddleware in MIDDLEWARE.
    """

    ALLOWED_PATHS = (
        '/accounts/blocked/',
        '/accounts/logout/',
        '/admin/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip allowed paths
        if any(request.path.startswith(p) for p in self.ALLOWED_PATHS):
            return self.get_response(request)

        # Check user block
        if request.user.is_blocked:
            # Auto-unblock expired temporary blocks
            if (request.user.block_type == 'temporary'
                    and request.user.block_expires_at
                    and timezone.now() > request.user.block_expires_at):
                request.user.is_blocked = False
                request.user.block_type = ''
                request.user.save(update_fields=['is_blocked', 'block_type'])
                return self.get_response(request)

            # Force logout and redirect
            from audit.services import log_event
            log_event(
                user=request.user, category='auth',
                action='blocked_user_access_attempt', result='blocked',
                request=request,
            )
            logout(request)
            return redirect('account_blocked')

        # Check school suspension
        from billing.entitlements import get_school_for_user
        school = get_school_for_user(request.user)
        if school and school.is_suspended:
            from audit.services import log_event
            log_event(
                user=request.user, school=school, category='auth',
                action='suspended_school_access_attempt', result='blocked',
                request=request,
            )
            logout(request)
            return redirect('account_blocked')

        return self.get_response(request)


class ProfileCompletionMiddleware:
    """
    Force new users (created by HoI) to change password and complete
    their profile before accessing the rest of the application.
    """

    ALLOWED_PATHS = (
        '/accounts/complete-profile/',
        '/accounts/logout/',
        '/accounts/blocked/',
        '/admin/',
        '/static/',
        '/stripe/',   # Stripe webhooks / redirects
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if any(request.path.startswith(p) for p in self.ALLOWED_PATHS):
            return self.get_response(request)

        if request.user.must_change_password or not request.user.profile_completed:
            return redirect('complete_profile')

        return self.get_response(request)


class SlowQueryLoggingMiddleware:
    """Log slow DB queries and query-heavy requests to the 'slow_queries' logger.

    Diagnostic instrumentation for DB pressure: without EXPLAIN access to the
    managed DB, this is how we find WHICH queries are expensive rather than
    guessing. Uses ``connection.execute_wrapper`` so it works with DEBUG off
    (``connection.queries`` is empty in production) at ~one time() call per
    query. Only the SQL *text* (placeholders, no bound params) is logged, so no
    row values / PII leak into the logs.

    Two signals, both threshold-gated so a healthy request logs nothing:
      * any single query >= SLOW_QUERY_MS (default 500 ms)
      * a request issuing >= QUERY_COUNT_WARN queries (default 50) — the classic
        N+1 fingerprint.

    Set SLOW_QUERY_MS <= 0 to disable entirely.
    """

    #: SQL is truncated to this many chars in the log line.
    _SQL_MAX = 500

    def __init__(self, get_response):
        self.get_response = get_response
        self.slow_ms = getattr(settings, 'SLOW_QUERY_MS', 500)
        self.count_warn = getattr(settings, 'QUERY_COUNT_WARN', 50)
        # Let Django drop this middleware from the chain when disabled, so there
        # is zero per-query overhead rather than a wrapper that checks a flag.
        if self.slow_ms <= 0:
            from django.core.exceptions import MiddlewareNotUsed
            raise MiddlewareNotUsed()

    def __call__(self, request):
        state = {'count': 0}
        slow_ms = self.slow_ms

        def wrapper(execute, sql, params, many, context):
            start = time.monotonic()
            try:
                return execute(sql, params, many, context)
            finally:
                state['count'] += 1
                elapsed_ms = (time.monotonic() - start) * 1000
                if elapsed_ms >= slow_ms:
                    _slow_query_log.warning(
                        'slow query %.0fms on %s %s: %s',
                        elapsed_ms, request.method, request.path,
                        sql[:self._SQL_MAX],
                    )

        with connection.execute_wrapper(wrapper):
            response = self.get_response(request)

        if state['count'] >= self.count_warn:
            _slow_query_log.warning(
                'high query count: %d queries on %s %s',
                state['count'], request.method, request.path,
            )
        return response
