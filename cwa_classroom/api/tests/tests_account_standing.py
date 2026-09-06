"""The account-standing codes are a contract with a client we cannot redeploy.

Each code routes the mobile app to a different "here is what to do about it"
screen. The app is a separate repository on an app-store release cycle, so a
code added here reaches a phone weeks later at best — and never on an install
nobody updates. A code the app does not recognise is not a cosmetic problem:
it cannot be told apart from an ordinary failure, so the app falls back to
signing the user out, and their correct password logs them straight back into
the same wall.

Nothing about adding a wall to ``cwa_classroom/middleware.py`` looks like an
API change — the schema does not move, so ``tests_schema.py`` stays green and
the diff touches no serializer. These tests are what makes it visible.
"""

import ast
from pathlib import Path

import pytest

from api.authentication import ACCOUNT_STANDING_CODES, ACCOUNT_STANDING_FALLBACK_CODE

MIDDLEWARE_PATH = (
    Path(__file__).resolve().parents[2] / 'cwa_classroom' / 'middleware.py'
)


def _wall_codes_in_middleware():
    """Every literal code passed to ``wall_response`` in the middleware.

    Read out of the source rather than by triggering each wall: driving all
    seven states through the ORM would be a slow, fragile test that still
    missed the eighth wall somebody adds next, because it would only check the
    ones it already knew to set up.
    """
    tree = ast.parse(MIDDLEWARE_PATH.read_text())
    codes = set()
    non_literal = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', None)
        if name != 'wall_response':
            continue
        # wall_response(request, code, detail, redirect_to)
        code_arg = node.args[1] if len(node.args) > 1 else None
        if isinstance(code_arg, ast.Constant) and isinstance(code_arg.value, str):
            codes.add(code_arg.value)
        else:
            non_literal.append(node.lineno)

    return codes, non_literal


def test_the_middleware_source_is_readable():
    """Guards the test itself: a moved middleware would silently check nothing."""
    assert MIDDLEWARE_PATH.exists(), f'No middleware at {MIDDLEWARE_PATH}'
    codes, _ = _wall_codes_in_middleware()
    assert codes, 'Found no wall_response() calls — has the wall helper been renamed?'


def test_every_wall_code_is_one_the_app_knows_about():
    codes, _ = _wall_codes_in_middleware()
    unknown = codes - set(ACCOUNT_STANDING_CODES)
    assert not unknown, (
        f'These walls emit codes the API does not declare: {sorted(unknown)}.\n'
        'Add them to api.authentication.ACCOUNT_STANDING_CODES, and add them to '
        'the mobile client too — an app that does not recognise a code cannot '
        'route the user anywhere useful, so it signs them out instead.')


def test_no_declared_code_is_unreachable():
    """The list must not accumulate codes nothing can emit.

    A stale entry is not harmless: it is a screen the app carries, and a
    reviewer reading the list is told the server can produce something it
    cannot.
    """
    codes, _ = _wall_codes_in_middleware()
    reachable = codes | {ACCOUNT_STANDING_FALLBACK_CODE}
    unreachable = set(ACCOUNT_STANDING_CODES) - reachable
    assert not unreachable, (
        f'Declared but emitted by nothing: {sorted(unreachable)}. '
        'Remove them, or point this test at whatever else raises them.')


def test_every_wall_code_is_a_literal():
    """A computed code cannot be checked by this test, so it is banned here.

    The point of the file is that the set of codes is knowable by reading; a
    code built at runtime puts a wall outside that guarantee.
    """
    _, non_literal = _wall_codes_in_middleware()
    assert not non_literal, (
        f'wall_response() called with a non-literal code at line(s) {non_literal}. '
        'Keep wall codes as string literals so they stay enumerable.')


@pytest.mark.parametrize('code', ACCOUNT_STANDING_CODES)
def test_the_error_handler_preserves_each_code(code):
    """``api.exceptions`` must pass a standing code through untouched.

    It is what stops these becoming a generic ``permission_denied``, which is
    the shape the app cannot act on.
    """
    from api.authentication import AccountStandingDenied
    from api.exceptions import _code_for

    assert _code_for(AccountStandingDenied(code, 'detail')) == code
