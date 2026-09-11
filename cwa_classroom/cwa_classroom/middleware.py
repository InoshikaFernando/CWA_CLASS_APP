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
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

_slow_query_log = logging.getLogger('slow_queries')


class MathsRoomRedirectMiddleware:
    """
    Permanently redirect mathsroom.wizardslearninghub.co.nz → /maths/

    A leftover from the subdomain-per-subject era. Subjects are served from
    paths now (/maths/, /coding/, …), and the urlconf-switching middleware
    that went with the subdomains has been removed — but this redirect stays.
    It is what keeps an old mathsroom bookmark working, and silently breaking
    links people already hold is the exact failure this codebase has just
    finished paying for once (see classroom.topic_redirect).
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


# ---------------------------------------------------------------------------
# Access walls: one rule, two audiences
# ---------------------------------------------------------------------------
# The three middlewares below (trial expiry, account block, unfinished profile)
# each end in a redirect to an HTML page. That is the right answer for a
# browser and the wrong one for the JSON API: a mobile client cannot render
# the page, and a 302 to a login-ish URL is not something it can branch on —
# it would read as success and show an empty screen.
#
# Rather than re-implement these rules inside the API (two copies of a
# permission rule eventually disagree, and the one that drifts is the one
# nobody is looking at), every wall funnels through `wall_response`. Browsers
# keep getting the redirect; /api/ gets a 403 carrying a machine-readable
# `code` the app can switch on.

API_PATH_PREFIX = '/api/'


def is_api_request(request):
    return request.path.startswith(API_PATH_PREFIX)


def wall_response(request, code, detail, redirect_to):
    """The redirect a browser expects, or the JSON an API client can act on.

    The JSON carries ``resolve_path``: the page that clears this particular
    wall. Some of these walls cannot be cleared through the API at all —
    finishing a student profile runs through the discount-code and Stripe flow
    in ``accounts.views.CompleteProfileView``, and paying an expired
    subscription is the billing pages — so the app opens that path in a
    webview rather than the API growing a second, drifting copy of a payment
    flow. Without it a walled client knows it is stuck but not what to do,
    which is a dead end wearing an error code.
    """
    if is_api_request(request):
        try:
            resolve_path = reverse(redirect_to)
        except NoReverseMatch:
            resolve_path = None
        return JsonResponse(
            {'error': {'code': code, 'detail': detail,
                       'resolve_path': resolve_path}},
            status=403,
        )
    return redirect(redirect_to)


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
        # A super admin viewing as an expired user must still be able to leave.
        '/accounts/stop-viewing-as/',
        '/billing/',
        '/stripe/',
        '/admin/',
        # The API's equivalent of the /accounts/logout/ and /billing/ escapes
        # above. Without it an expired account is 403'd on its own logout
        # endpoint and can never revoke a refresh token that stays valid for
        # thirty days — the wall would be keeping the token alive.
        '/api/v1/auth/logout/',
        '/api/v1/auth/me/',
        '/api/v1/auth/refresh/',
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
                    return wall_response(
                        request, 'subscription_required',
                        'This account has no active subscription.',
                        'trial_expired')
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
                    return wall_response(
                        request, 'trial_expired',
                        'Your subscription has expired. Renew to continue.',
                        'trial_expired')

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
                return wall_response(
                    request, 'school_subscription_expired',
                    "Your school's subscription has expired.",
                    'institute_trial_expired')

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
            return wall_response(
                request, 'payment_required',
                'Your subscription payment is overdue.',
                'trial_expired')
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
        # A super admin viewing as a blocked user must still be able to leave.
        '/accounts/stop-viewing-as/',
        '/admin/',
        # Logout only — the API mirror of /accounts/logout/ above. A blocked
        # account must still be able to revoke its own refresh token; it gets
        # a coded 403 everywhere else, including /auth/me/.
        '/api/v1/auth/logout/',
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
            # While a super admin is viewing as this user, logout() would flush
            # the ADMIN's session, not the target's — so show the block screen
            # instead and leave the "Stop" banner working.
            # An API caller holds a bearer token, not a session, so there is
            # no session to flush — and logout() would drop the session of a
            # browser that happens to share the request. The token is rejected
            # on every call for as long as the block stands.
            if not is_api_request(request) and not getattr(request, 'is_impersonating', False):
                logout(request)
            return wall_response(
                request, 'account_blocked',
                'This account has been blocked. Contact your school administrator.',
                'account_blocked')

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
            if not is_api_request(request) and not getattr(request, 'is_impersonating', False):
                logout(request)
            return wall_response(
                request, 'school_suspended',
                'Your school account has been suspended.',
                'account_blocked')

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
        # A super admin viewing as a half-onboarded user must still be able to leave.
        '/accounts/stop-viewing-as/',
        '/admin/',
        '/static/',
        '/stripe/',   # Stripe webhooks / redirects
        # The API's equivalent of /accounts/complete-profile/. These are the
        # endpoints the app uses to GET what is missing, PATCH it, and change
        # the temporary password — wall them and a newly-created student is
        # locked out of the only screens that could let them in.
        # Deliberately only this wall: a BLOCKED account still gets nothing.
        '/api/v1/auth/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if any(request.path.startswith(p) for p in self.ALLOWED_PATHS):
            return self.get_response(request)

        if request.user.must_change_password or not request.user.profile_completed:
            return wall_response(
                request, 'profile_incomplete',
                'Finish setting up your profile before continuing.',
                'complete_profile')

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
