"""Template lint: a developer note must never reach a student's screen.

Django's ``{# … #}`` comment is a SINGLE-LINE construct. Its lexer matches
``{#.*?#}`` without ``re.DOTALL``, so the moment a comment wraps onto a second
line it stops being a comment and the whole thing is rendered as page text.
Nothing goes red — the page still returns 200 — it just prints the note.

That is how "{# A part-graded question (fill-in-the-blank, table of values) can
be marked partly right… #}" came to sit between the Mark button and the result
box on the preview-as-a-student modal, and the same defect was live in the
worksheet answer feedback and quiz review pages, which students read.

These tests run in the migration-check job, which is deliberately ungated, so
they execute on every push and pull request — a template is not covered by any
app's unit suite.
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {'node_modules', 'staticfiles', '.venv', '__pycache__'}

# The opening of a Django comment. Everything up to the matching '#}' is the
# body; a newline anywhere in it means Django will not treat it as a comment.
_COMMENT_OPEN = '{#'
_COMMENT_CLOSE = '#}'


def _template_files():
    return sorted(
        path for path in PROJECT_ROOT.rglob('*.html')
        if not SKIP_DIRS & set(path.parts)
    )


def _leaked_comments(text):
    """Every ``{# … #}`` in ``text`` that Django will print rather than hide."""
    leaks = []
    index = 0
    while True:
        start = text.find(_COMMENT_OPEN, index)
        if start == -1:
            return leaks
        end = text.find(_COMMENT_CLOSE, start)
        line = text.count('\n', 0, start) + 1
        if end == -1:
            # Never closed — every character after it renders as page text.
            leaks.append((line, text[start:start + 60], 'never closed'))
            return leaks
        body = text[start + len(_COMMENT_OPEN):end]
        if '\n' in body:
            leaks.append((line, body.strip().split('\n')[0][:60], 'spans lines'))
        index = end + len(_COMMENT_CLOSE)


def test_there_are_templates_to_check():
    # A glob that matches nothing would make the check below vacuously pass.
    assert _template_files(), f'No templates found under {PROJECT_ROOT}'


@pytest.mark.parametrize(
    'path', _template_files(),
    ids=lambda p: p.relative_to(PROJECT_ROOT).as_posix())
def test_no_template_comment_is_rendered_to_the_page(path):
    leaks = _leaked_comments(path.read_text(encoding='utf-8'))
    assert not leaks, (
        f'{path.relative_to(PROJECT_ROOT)} prints developer notes to the page:\n  '
        + '\n  '.join(f'line {line}: {{# {snippet}… ({why})'
                      for line, snippet, why in leaks)
        + "\n\nDjango's {# #} comment is single-line only. Use "
          '{% comment %} … {% endcomment %} for anything longer.')


def test_the_check_catches_a_multi_line_comment():
    # The guard is itself guarded: a check that cannot fail proves nothing.
    assert _leaked_comments('{# one\n   two #}')
    assert _leaked_comments('{# never closed')
    assert not _leaked_comments('{# on one line #}')
    assert not _leaked_comments('{% comment %}\none\ntwo\n{% endcomment %}')


# Multi-line ``{# … #}`` in the same file that DEFINES the check would make the
# parametrised test above fail on this very module's docstring examples, which
# is why the examples live in string literals rather than in a template.
def test_the_rule_matches_djangos_own_lexer():
    """Pinned to Django itself, not to a belief about it.

    If a future Django made ``{# … #}`` multi-line, this rule would be pointless
    ceremony — so the assumption is checked against the engine's own regex.
    """
    from django.template.base import tag_re
    assert not (tag_re.flags & re.DOTALL), (
        'Django now lexes tags with DOTALL — multi-line {# #} may be a real '
        'comment, so this whole check can go.')
