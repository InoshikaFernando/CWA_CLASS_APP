"""
Super-admin "View as" — browse the site exactly as one real student, teacher
or parent sees it.

Why swap ``request.user`` rather than reuse the role switcher
-------------------------------------------------------------
The existing ``session['active_role']`` switcher (``SwitchRoleView``) cannot
answer "what does this family actually see?" for two reasons:

1. It only accepts a role the *logged-in* user holds, and a super admin holds
   none of them.
2. Superusers bypass the checks that shape a real user's page.
   ``RoleRequiredMixin`` skips role enforcement for them entirely, and data
   helpers widen for them — ``classroom.views._get_user_school_ids`` returns
   *every* school, and ``if user.is_superuser:`` branches appear throughout
   ``views_reports``, ``views_department``, ``progress.access`` and others.

So a super admin "switched to student" would still be served admin-sized data.
The only faithful answer is for ``request.user`` to *be* the target user for
the duration of the request.

Shape of the mechanism
----------------------
* The session keeps the target's id plus the impersonator's id and a start
  timestamp. ``ImpersonationMiddleware`` re-reads them on every request,
  re-verifies the impersonator is *still* a superuser, and swaps
  ``request.user`` in place.
* We deliberately do NOT call ``django.contrib.auth.login()`` to switch. That
  cycles the session key and destroys the anchor back to the real account;
  swapping on the request object means "stop" is a session pop and the real
  login is never touched.
* Impersonation is **read-only**: unsafe HTTP methods are refused. A student
  session can submit homework and sit quizzes, and a parent session can pay an
  invoice through Stripe — none of which should ever happen because an admin
  was looking around. Viewing is what this feature is for.
"""
import logging

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)

# Session keys. IMPERSONATOR_KEY is the anchor back to the real account; if it
# is missing the middleware refuses to impersonate at all.
TARGET_KEY = 'impersonate_user_id'
IMPERSONATOR_KEY = 'impersonator_id'
STARTED_AT_KEY = 'impersonation_started_at'
# The impersonator's own active_role, parked while they are viewing as someone
# else. See _apply_target_role() for why the session value is rewritten.
SAVED_ROLE_KEY = 'impersonation_saved_active_role'

# URL the banner's "Stop" button posts to. Kept as a literal (not reverse())
# because middleware path checks run before URL resolution.
STOP_PATH = '/accounts/stop-viewing-as/'

# Paths that keep working with an unsafe method while impersonating — you must
# always be able to get back out.
WRITE_ALLOWED_PATHS = (STOP_PATH, '/accounts/logout/')

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS', 'TRACE')

# Impersonation expires on its own so a forgotten tab cannot leave a super
# admin wandering a child's account for the rest of the day.
DEFAULT_MAX_SECONDS = 30 * 60


def max_seconds():
    return getattr(settings, 'IMPERSONATION_MAX_SECONDS', DEFAULT_MAX_SECONDS)


def can_impersonate(user):
    """Only platform super admins. Note Role.ADMIN is a *school* admin here —
    a tenant — so it is deliberately not enough."""
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and user.is_superuser
        and user.is_active
    )


def is_impersonatable(target, actor):
    """Return (ok, reason). Staff/superusers are excluded: impersonating a peer
    admin would be a privilege-laundering path that leaves the audit trail
    pointing at the wrong person."""
    if target is None:
        return False, 'That user no longer exists.'
    if not target.is_active:
        return False, 'That account is inactive.'
    if actor is not None and target.pk == actor.pk:
        return False, 'You are already yourself.'
    if target.is_superuser or target.is_staff:
        return False, 'Staff and super admin accounts cannot be viewed as.'
    return True, ''


def start(request, target):
    """Begin impersonating ``target``. Caller must have checked permission."""
    actor = request.user
    request.session[TARGET_KEY] = target.pk
    request.session[IMPERSONATOR_KEY] = actor.pk
    request.session[STARTED_AT_KEY] = timezone.now().isoformat()
    _apply_target_role(request.session, target)

    from audit.services import log_event
    log_event(
        user=actor, category='admin_action', action='impersonation_started',
        detail={
            'target_user_id': target.pk,
            'target_username': target.username,
            'target_role': target.primary_role,
        },
        request=request,
    )


def stop(request):
    """End impersonation and hand the session back to the real account.

    Returns the impersonated user (or None if nothing was in progress) so the
    caller can name them in a confirmation message.
    """
    session = request.session
    target_id = session.get(TARGET_KEY)
    if target_id is None:
        return None

    from .models import CustomUser
    target = CustomUser.objects.filter(pk=target_id).first()
    actor = getattr(request, 'impersonator', None) or request.user

    _clear(session)
    # Impersonation is over as of now, so drop the request flags before logging:
    # otherwise log_event's impersonation override would file this event as
    # "the admin, acting as the admin".
    request.impersonator = None
    request.is_impersonating = False

    from audit.services import log_event
    log_event(
        user=actor, category='admin_action', action='impersonation_stopped',
        detail={
            'target_user_id': target_id,
            'target_username': target.username if target else None,
        },
        request=request,
    )
    return target


def _clear(session):
    """Drop every impersonation key and restore the impersonator's own role."""
    saved_role = session.get(SAVED_ROLE_KEY)
    for key in (TARGET_KEY, IMPERSONATOR_KEY, STARTED_AT_KEY, SAVED_ROLE_KEY):
        session.pop(key, None)
    if saved_role:
        session['active_role'] = saved_role
    else:
        session.pop('active_role', None)


def _apply_target_role(session, target):
    """Park the impersonator's ``active_role`` and install the target's own.

    ``active_role`` is read straight out of the session in several places
    (``accounts.context_processors.user_role``, ``help.views``,
    ``classroom.views``). Rewriting the one session value keeps every one of
    those readers correct without touching them, and ``_clear()`` puts the
    impersonator's own role back when they stop.
    """
    if 'active_role' in session and SAVED_ROLE_KEY not in session:
        session[SAVED_ROLE_KEY] = session['active_role']
    target_role = target.primary_role
    if target_role:
        session['active_role'] = target_role
    else:
        session.pop('active_role', None)


def _expired(session):
    started = session.get(STARTED_AT_KEY)
    if not started:
        return True
    from django.utils.dateparse import parse_datetime
    started_at = parse_datetime(started)
    if started_at is None:
        return True
    return (timezone.now() - started_at).total_seconds() > max_seconds()


class ImpersonationMiddleware:
    """Swap ``request.user`` for the impersonated user, read-only.

    Registered above the app's own middleware so every one of them — and every
    view — sees the swapped user. That is the whole point: the trial-expiry
    wall and the account-block screen should be the ones the *target* hits, not
    the ones a super admin would. See MIDDLEWARE in settings for the exact slot
    and why it sits where it does.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set on every request so templates and other middleware can rely on
        # them existing without getattr defaults everywhere.
        request.impersonator = None
        request.is_impersonating = False

        session = getattr(request, 'session', None)
        if session is None or session.get(TARGET_KEY) is None:
            return self.get_response(request)

        actor = self._resolve_actor(request)
        if actor is None:
            # Not a superuser any more (demoted, deactivated, or the session
            # was carried onto a different login) — drop it silently.
            _clear(session)
            return self.get_response(request)

        if _expired(session):
            target_id = session.get(TARGET_KEY)
            _clear(session)
            from audit.services import log_event
            log_event(
                user=actor, category='admin_action', action='impersonation_expired',
                detail={'target_user_id': target_id}, request=request,
            )
            from django.contrib import messages
            messages.info(request, 'Your "view as" session expired. You are back on your own account.')
            return self.get_response(request)

        from .models import CustomUser
        target = CustomUser.objects.filter(pk=session[TARGET_KEY]).first()
        ok, reason = is_impersonatable(target, actor)
        if not ok:
            _clear(session)
            from django.contrib import messages
            messages.warning(request, f'Stopped viewing as another user: {reason}')
            return self.get_response(request)

        request.user = target
        request.impersonator = actor
        request.is_impersonating = True

        if not self._write_allowed(request):
            return self._refuse_write(request, target)

        return self.get_response(request)

    @staticmethod
    def _resolve_actor(request):
        """The real, logged-in super admin behind this session — or None.

        Re-checked on every request rather than trusted from the session, so
        revoking someone's superuser flag ends any impersonation they have open
        on their very next page load.
        """
        session = request.session
        actor = request.user
        actor_id = session.get(IMPERSONATOR_KEY)
        if actor_id is None or not getattr(actor, 'is_authenticated', False):
            return None
        if actor.pk != actor_id:
            return None
        if not can_impersonate(actor):
            return None
        return actor

    @staticmethod
    def _write_allowed(request):
        if request.method in SAFE_METHODS:
            return True
        return request.path in WRITE_ALLOWED_PATHS

    @staticmethod
    def _refuse_write(request, target):
        """Block the write and say why, rather than failing silently."""
        logger.info(
            'Blocked %s %s during impersonation of %s',
            request.method, request.path, target.username,
        )
        if getattr(request, 'htmx', False) or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponse(
                'Read-only: you are viewing this page as another user.',
                status=403,
            )
        return render(
            request,
            'accounts/impersonation_read_only.html',
            {'target_user': target, 'blocked_path': request.path},
            status=403,
        )
