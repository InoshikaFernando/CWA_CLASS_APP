"""
Context builders for the shared coding window.

The window itself is ``templates/coding/partials/_code_window.html`` (behaviour
in ``static/js/code_window.js``). This module turns a :class:`CodingExercise`
into the parameters that template expects, so every page that wants to show an
exercise in the editor — the worksheet-builder preview a teacher opens while
authoring, and anything that follows it — describes the exercise the same way.

Per language:

===========  ==========  ============================================
Language     Mode        Notes
===========  ==========  ============================================
python       run         starter code → Piston, stdout in the console
javascript   run         starter code → Piston, stdout in the console
html         preview     rendered in a sandboxed iframe, never executed
css          preview     rendered in a sandboxed iframe, never executed
scratch      *(none)*    block-based; a text editor would be wrong
===========  ==========  ============================================

An exercise with ``uses_browser_sandbox`` set overrides its language and always
renders as a preview — that flag exists for DOM exercises filed under a
non-browser language.
"""

from .models import CodingLanguage

# language slug → (code-window mode, CodeMirror mode, editor filename)
_LANGUAGE_WINDOW = {
    CodingLanguage.PYTHON:     ('run',     'python',     'main.py'),
    CodingLanguage.JAVASCRIPT: ('run',     'javascript', 'main.js'),
    CodingLanguage.HTML:       ('preview', 'htmlmixed',  'index.html'),
    CodingLanguage.CSS:        ('preview', 'css',        'style.css'),
}


def supports_code_window(exercise):
    """True when this exercise can be shown in the coding window.

    False for Scratch (block-based, so a text editor would misrepresent it)
    and for quiz-style exercises (multiple choice, true/false, short answer,
    fill in the blank) — those have no code to run.
    """
    if exercise.question_type != exercise.WRITE_CODE:
        return False
    return exercise.topic_level.topic.language.slug in _LANGUAGE_WINDOW


def window_context_for_exercise(exercise, run_url):
    """Return the ``_code_window.html`` parameters for ``exercise``.

    ``run_url`` is the endpoint the Run button posts to — teacher-facing
    callers pass ``coding:api_preview_run`` so nothing is recorded against a
    student. Returns ``None`` when the exercise has no meaningful window
    (see :func:`supports_code_window`).
    """
    if not supports_code_window(exercise):
        return None

    language = exercise.topic_level.topic.language
    mode, cm_mode, filename = _LANGUAGE_WINDOW[language.slug]

    # A DOM exercise filed under JavaScript still renders in the browser.
    if exercise.uses_browser_sandbox:
        mode, cm_mode, filename = 'preview', 'htmlmixed', 'index.html'

    context = {
        'cw_mode': mode,
        'cw_language': language.slug,
        'cw_lang_label': language.name,
        'cw_cm_mode': cm_mode,
        'cw_filename': filename,
        'cw_run_url': run_url,
        'cw_starter': '',
        'cw_starter_html': '',
        'cw_starter_css': '',
        # Only the console can report a match, and only against real text.
        'cw_expected_output': exercise.expected_output if mode == 'run' else '',
    }

    if mode == 'preview':
        key = 'cw_starter_css' if cm_mode == 'css' else 'cw_starter_html'
        context[key] = exercise.starter_code
    else:
        context['cw_starter'] = exercise.starter_code

    return context
