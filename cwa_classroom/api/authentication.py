"""Bearer-token authentication that also applies the app's access walls.

Why this lives in the authentication layer rather than in a permission class:

The web app puts three walls in front of a signed-in user — expired
subscription, blocked account, unfinished profile — implemented as middleware
in ``cwa_classroom.middleware``. Middleware cannot enforce them for the API,
because Django resolves ``request.user`` from the *session* and a bearer-token
request has none: every wall sees ``AnonymousUser`` and waves the request
through, long before DRF has looked at the token.

The obvious fix is a permission class, and it is a trap. DRF's
``DEFAULT_PERMISSION_CLASSES`` is replaced wholesale — not extended — by any
view that sets ``permission_classes``, which nearly every non-trivial view
does. The wall would silently stop applying to exactly the endpoints someone
bothered to think about.

An authentication class cannot be opted out of the same way: a view that names
``permission_classes`` still authenticates through here. So the walls run once,
at the point the token is turned into a user, and no endpoint can forget them.

The rules themselves are NOT reimplemented — the real middlewares are executed
(they are plain callables over a Django request). Their subscription cascade
alone spans individual, self-paying and school plans, auto-expires a lapsed
trial and audit-logs each denial; a second copy of that would drift, and the
copy that drifts is the one nobody is reading.
"""

import json

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class AccountStandingDenied(PermissionDenied):
    """403 naming the wall the caller hit, so the app can route to it.

    ``api.exceptions`` reads ``standing_code`` and puts it in the error
    envelope, so the client sees ``trial_expired`` rather than a flat
    ``permission_denied`` it cannot act on.
    """

    def __init__(self, code, detail, resolve_path=None):
        super().__init__(detail=detail)
        self.standing_code = code
        # The page that clears this wall. Carried through so a token-
        # authenticated caller gets the same envelope a session one does —
        # without it the JWT path silently drops the only field telling the
        # app where to send the user.
        self.resolve_path = resolve_path


# Every account-standing code the API can answer with.
#
# This is the contract the mobile app switches on: each code routes to a
# different "here is what to do about it" screen, so an app that does not
# recognise one cannot act on it. The app is a separate repository on a store
# release cycle, so a code added here reaches a phone weeks later at best, and
# never on installs that are not updated.
#
# `tests_account_standing.py` reads the wall call sites out of the middleware
# and fails if this list and those walls disagree, so adding a wall without
# adding it here is a red build rather than a client that signs the user out
# when it meets an error it cannot name.
ACCOUNT_STANDING_CODES = (
    'subscription_required',
    'trial_expired',
    'school_subscription_expired',
    'payment_required',
    'account_blocked',
    'school_suspended',
    'profile_incomplete',
    # Not a wall of its own: what a wall degrades to when its envelope cannot
    # be parsed. Still a denial, and still something the app must recognise.
    'access_denied',
)

#: What an unparseable wall degrades to. Part of the tuple above.
ACCOUNT_STANDING_FALLBACK_CODE = 'access_denied'


_PASSED_THROUGH = object()

# Ordered as in settings.MIDDLEWARE, so a user behind two walls is told about
# the same one the website would have shown them.
def _wall_middleware_classes():
    from cwa_classroom.middleware import (
        AccountBlockMiddleware, ProfileCompletionMiddleware, TrialExpiryMiddleware,
    )
    return (TrialExpiryMiddleware, AccountBlockMiddleware, ProfileCompletionMiddleware)


def first_wall(django_request):
    """The response of the first wall that stops this request, or None."""
    for middleware_class in _wall_middleware_classes():
        instance = middleware_class(lambda _request: _PASSED_THROUGH)
        result = instance(django_request)
        if result is not _PASSED_THROUGH:
            return result
    return None


def _read_envelope(response):
    """Pull code/detail back out of the middleware's JSON wall response."""
    try:
        error = json.loads(response.content.decode())['error']
        return error['code'], error['detail'], error.get('resolve_path')
    except (ValueError, KeyError, UnicodeDecodeError):
        # A wall we cannot parse is still a wall: deny, but do not invent a
        # reason for it.
        return (ACCOUNT_STANDING_FALLBACK_CODE,
                'This account cannot use the API right now.', None)


class WalledJWTAuthentication(JWTAuthentication):
    """``JWTAuthentication`` plus the account-standing walls."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            # No bearer token on this request — let the next authenticator try.
            return None

        user, validated_token = result

        # The walls read request.user; the Django request underneath still has
        # the AnonymousUser that AuthenticationMiddleware left there.
        django_request = getattr(request, '_request', request)
        previous = getattr(django_request, 'user', None)
        django_request.user = user
        try:
            response = first_wall(django_request)
        finally:
            if previous is not None:
                django_request.user = previous

        if response is not None:
            raise AccountStandingDenied(*_read_envelope(response))

        return user, validated_token
