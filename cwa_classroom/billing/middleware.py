"""Deny-by-default module enforcement, with a shadow mode to land it safely.

Why middleware and not another mixin: ``ModuleRequiredMixin`` is a Django CBV
hook. It cannot gate a function-based view generically, and it does nothing at
all for a DRF viewset — which matters because ``api/urls.py`` deliberately
centralises every app's viewsets into one router, making ``/api/v1/`` a
complete second copy of the product surface. One ``process_view`` hook sees
all three.

``process_view`` and not ``__call__``: the module a request needs is a
property of the matched *route*, and ``request.resolver_match`` is not
populated until Django has resolved the URL.

**Three modes**, because switching this on is the part that can hurt:

``off``
    Does nothing. The per-view mixins still enforce, exactly as before.
``shadow`` (the default)
    Resolves the decision and records every would-be denial to the audit log,
    but allows the request. This is how you find out which paying schools your
    registry is wrong about, before it costs them a support ticket rather than
    a log line.
``enforce``
    Blocks.

Shadow mode is the default deliberately. Several modules in the registry
describe features that are free today — turning them off is a commercial
decision with real customers behind it, and it should be somebody's explicit
act after reading a week of shadow data, not a side effect of deploying this
file.
"""

import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode

from billing import registry
from billing.entitlements import entitled_modules

logger = logging.getLogger(__name__)

OFF = 'off'
SHADOW = 'shadow'
ENFORCE = 'enforce'


def _mode():
    """Read the mode each request rather than at import.

    So a deploy can flip it with an env var and a restart, and so a test can
    override_settings without reloading the middleware.
    """
    mode = getattr(settings, 'MODULE_ENFORCEMENT', SHADOW)
    return mode if mode in (OFF, SHADOW, ENFORCE) else SHADOW


class ModuleEnforcementMiddleware:
    """Resolve the module a route needs and act on it.

    Position in MIDDLEWARE is load-bearing: below ImpersonationMiddleware so
    "view as" is honoured (a super admin viewing a school sees that school's
    entitlements), and above UsageTrackingMiddleware so a blocked request is
    recorded as blocked rather than as a page view.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    # -- the hook --------------------------------------------------------

    def process_view(self, request, view_func, view_args, view_kwargs):
        mode = _mode()
        if mode == OFF:
            return None

        match = getattr(request, 'resolver_match', None)
        if match is None:
            return None

        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            # Anonymous traffic is the login and marketing surface. Whether it
            # may see a page is authentication's question, not billing's.
            return None
        if user.is_superuser:
            return None

        module = self._module_for(request, view_func, match)
        if module is None:
            return None
        if module in entitled_modules(request):
            return None

        self._record(request, module, match, blocked=(mode == ENFORCE))

        if mode == SHADOW:
            return None
        return self._deny(request, module)

    # -- resolution ------------------------------------------------------

    def _module_for(self, request, view_func, match):
        """Which module this route needs, or None for the base product.

        Order matters. The view's own ``required_module`` is read first so the
        markers that already exist stay authoritative and can never disagree
        with the registry; only then do the registry's rules apply.
        """
        view_class = getattr(view_func, 'view_class', None) or getattr(view_func, 'cls', None)

        declared = registry.module_for_view(view_class)
        if declared:
            return declared

        by_name = registry.module_for_route(match.namespace, match.url_name)
        if by_name:
            return by_name

        # DRF routes are named "<basename>-list" / "<basename>-detail".
        return registry.module_for_api_basename(self._basename(match.url_name))

    @staticmethod
    def _basename(url_name):
        if not url_name:
            return None
        for suffix in ('-list', '-detail'):
            if url_name.endswith(suffix):
                return url_name[: -len(suffix)]
        return None

    # -- outcomes --------------------------------------------------------

    def _record(self, request, module, match, blocked):
        """Log the decision. In shadow mode this IS the deliverable.

        Audit failures must never take a request down with them — in shadow
        mode especially, where the request was going to be allowed anyway.
        """
        try:
            from audit.services import log_event
            log_event(
                user=request.user,
                category='entitlement',
                action='module_access_denied' if blocked else 'module_access_would_deny',
                result='blocked' if blocked else 'allowed',
                detail={
                    'module': module,
                    'route': f'{match.namespace}:{match.url_name}' if match.namespace
                             else (match.url_name or request.path),
                    'path': request.path,
                    'mode': _mode(),
                },
                request=request,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                'entitlement audit failed for module=%s path=%s',
                module, request.path, exc_info=True,
            )

    def _deny(self, request, module):
        """One rule, two audiences — the split middleware.py already makes.

        A 302 to an HTML upsell page is right for a browser and useless to the
        mobile client, which cannot render it and would read the redirect as
        success. 402 is the branchable answer, and names the module so the
        client can say what to buy.
        """
        if request.path.startswith('/api/'):
            return JsonResponse(
                {
                    'detail': 'This feature is not included in your plan.',
                    'code': 'module_required',
                    'module': module,
                },
                status=402,
            )
        try:
            url = reverse('module_required')
        except Exception:  # noqa: BLE001
            return JsonResponse(
                {'detail': 'This feature is not included in your plan.',
                 'code': 'module_required', 'module': module},
                status=402,
            )
        return redirect(f'{url}?{urlencode({"module": module})}')
