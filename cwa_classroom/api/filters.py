"""Query-parameter helpers.

Every list endpoint takes ids as query strings (``?student=12``). Passing
those straight into ``filter(student_id=...)`` means ``?student=abc`` raises
``ValueError`` deep in the ORM — and because ``api.exceptions`` deliberately
lets unrecognised exceptions through to Django (so real bugs are not hidden
behind a tidy 500), the caller gets an unhandled server error for what is
plainly a bad request.

``int_param`` turns that into a 400 the client can act on.
"""

from rest_framework.exceptions import ValidationError


def int_param(params, name):
    """Return ``params[name]`` as an int, or None when absent/blank.

    Raises DRF's ValidationError — a 400 with the offending field named —
    rather than letting a non-numeric value reach the query.
    """
    raw = params.get(name)
    if raw is None or raw == '':
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: [f'Must be a whole number, got {raw!r}.']})


def bool_param(params, name):
    """True only for the affirmative spellings; absent or anything else is False."""
    return params.get(name) in ('1', 'true', 'True', 'yes')
