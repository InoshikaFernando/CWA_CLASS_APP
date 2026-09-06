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

# Console mode keeps one editor for every language, because the page around it
# owns a single ``code_<id>`` form field. Scratch's generated code is Python.
_CONSOLE_WINDOW = {
    CodingLanguage.PYTHON:     ('python',     'main.py'),
    CodingLanguage.JAVASCRIPT: ('javascript', 'main.js'),
    CodingLanguage.HTML:       ('htmlmixed',  'index.html'),
    CodingLanguage.CSS:        ('css',        'style.css'),
    CodingLanguage.SCRATCH:    ('python',     'main.py'),
}

AUTO = 'auto'
CONSOLE = 'console'


def supports_code_window(exercise, mode=AUTO):
    """True when this exercise can be shown in the coding window.

    Quiz-style exercises (multiple choice, true/false, short answer, fill in
    the blank) never qualify — there is no code to run.

    In ``auto`` mode Scratch is also excluded: it is block-based, and a text
    editor would misrepresent it. ``console`` mode takes it, because the pages
    that ask for console mode submit the code as a form field and have always
    shown Scratch its generated Python.
    """
    if exercise.question_type != exercise.WRITE_CODE:
        return False
    table = _CONSOLE_WINDOW if mode == CONSOLE else _LANGUAGE_WINDOW
    return exercise.topic_level.topic.language.slug in table


def window_context_for_exercise(exercise, run_url, mode=AUTO):
    """Return the ``_code_window.html`` parameters for ``exercise``.

    ``run_url`` is the endpoint the Run button posts to — teacher-facing
    callers pass ``coding:api_preview_run`` so nothing is recorded against a
    student; the homework and worksheet pages pass ``coding:api_run_code``.

    ``mode`` is ``auto`` (browser languages render as a live preview) or
    ``console`` (always one editor and a console). Pages that submit the code
    as a form field want ``console``: a preview needs two editors for HTML and
    CSS, and only one of them could carry the field's name.

    Returns ``None`` when the exercise has no meaningful window — see
    :func:`supports_code_window`.
    """
    if not supports_code_window(exercise, mode):
        return None

    language = exercise.topic_level.topic.language

    if mode == CONSOLE:
        cm_mode, filename = _CONSOLE_WINDOW[language.slug]
        window_mode = 'run'
    else:
        window_mode, cm_mode, filename = _LANGUAGE_WINDOW[language.slug]
        # A DOM exercise filed under JavaScript still renders in the browser.
        if exercise.uses_browser_sandbox:
            window_mode, cm_mode, filename = 'preview', 'htmlmixed', 'index.html'

    context = {
        'cw_mode': window_mode,
        'cw_language': language.slug,
        'cw_lang_label': language.name,
        'cw_cm_mode': cm_mode,
        'cw_filename': filename,
        'cw_run_url': run_url,
        'cw_starter': '',
        'cw_starter_html': '',
        'cw_starter_css': '',
        # Only the console can report a match, and only against real text.
        'cw_expected_output': (
            exercise.expected_output if window_mode == 'run' else ''
        ),
    }

    if window_mode == 'preview':
        key = 'cw_starter_css' if cm_mode == 'css' else 'cw_starter_html'
        context[key] = exercise.starter_code
    else:
        context['cw_starter'] = exercise.starter_code

    return context
