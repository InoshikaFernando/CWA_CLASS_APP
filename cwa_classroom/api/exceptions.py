"""One error shape for every failure the API can produce.

A mobile client has to branch on failures, and DRF's default output is not
uniform: a validation error is a dict of field lists, a 404 is
``{"detail": ...}``, a throttle adds ``wait``. Parsing three shapes in
Swift/Kotlin means three chances to get it wrong, so everything is normalised
to::

    {"error": {"code": "validation_error",
               "detail": "...",
               "fields": {"due_date": ["This field is required."]}}}

``code`` is the stable, machine-readable part — it is what the app switches
on. ``detail`` is human-readable and may be reworded without notice.
``fields`` is present only for validation errors.

The wall responses in ``cwa_classroom.middleware`` emit the same envelope, so
"blocked account" and "bad payload" look alike to the client's parser.
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger('api')

# DRF's own default_code values are already good identifiers; these fill in
# the cases where the default is vague or where we want a stabler name.
_CODE_OVERRIDES = {
    exceptions.ValidationError: 'validation_error',
    exceptions.NotAuthenticated: 'not_authenticated',
    exceptions.AuthenticationFailed: 'authentication_failed',
    exceptions.PermissionDenied: 'permission_denied',
    exceptions.NotFound: 'not_found',
    exceptions.MethodNotAllowed: 'method_not_allowed',
    exceptions.Throttled: 'rate_limited',
    exceptions.ParseError: 'parse_error',
}


def _code_for(exc):
    # A wall reported by api.permissions.AccountStanding already knows exactly
    # which state it is (trial_expired, account_blocked, ...). That is more
    # useful to the client than the generic 'permission_denied' its base class
    # would otherwise map to, so it wins.
    standing_code = getattr(exc, 'standing_code', None)
    if standing_code:
        return standing_code
    for exc_type, code in _CODE_OVERRIDES.items():
        if isinstance(exc, exc_type):
            return code
    code = getattr(exc, 'default_code', None) or getattr(exc, 'code', None)
    return str(code) if code else 'error'


def _flatten_detail(detail):
    """Best-effort single human-readable sentence out of a DRF detail blob."""
    if isinstance(detail, (list, tuple)):
        return _flatten_detail(detail[0]) if detail else ''
    if isinstance(detail, dict):
        for value in detail.values():
            flattened = _flatten_detail(value)
            if flattened:
                return flattened
        return ''
    return str(detail)


def api_exception_handler(exc, context):
    """DRF ``EXCEPTION_HANDLER`` — see the module docstring."""
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)

    if response is None:
        # Nothing DRF recognises — an unhandled bug. Let Django's own handler
        # produce the 500 so Sentry/logging and DEBUG tracebacks still work;
        # returning a tidy JSON 500 here would hide the failure, which is
        # exactly what this project's "no silent failure" rule forbids.
        logger.exception(
            'Unhandled API exception in %s',
            context.get('view').__class__.__name__ if context.get('view') else '?',
        )
        return None

    code = _code_for(exc)
    error = {'code': code, 'detail': _flatten_detail(response.data)}

    if isinstance(exc, exceptions.ValidationError):
        detail = exc.detail
        # A serializer error is a dict of field -> [messages]; a validate()
        # failure raised on the whole object is a bare list. Keep both, but
        # only under `fields` when it really is per-field.
        if isinstance(detail, dict):
            error['fields'] = detail
            error['detail'] = 'One or more fields are invalid.'
    if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
        error['retry_after_seconds'] = int(exc.wait)

    return Response({'error': error}, status=response.status_code,
                    headers=_headers_of(response))


def _headers_of(response):
    """Preserve headers DRF set on the original response (e.g. Retry-After)."""
    return {
        key: value for key, value in response.items()
        if key.lower() in ('retry-after', 'www-authenticate')
    }
