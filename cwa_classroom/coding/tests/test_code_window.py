"""
Tests for the shared coding window — the editor-plus-console component that
several pages render (the standalone compilers, the worksheet builder's
preview) instead of each hand-rolling its own.

Covers:
  - the reusable partials and their assets
  - coding.code_window.window_context_for_exercise, which maps an exercise
    onto the partial's parameters
  - api_preview_run, the teacher-facing runner that records nothing
"""
import json
import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from coding.code_window import supports_code_window, window_context_for_exercise
from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingTimeLog,
    CodingTopic,
    StudentExerciseSubmission,
    TopicLevel,
)

TEMPLATES_DIR = Path(settings.BASE_DIR) / 'templates'
HEAD_PARTIAL = TEMPLATES_DIR / 'coding' / 'partials' / '_code_window_head.html'
WINDOW_PARTIAL = TEMPLATES_DIR / 'coding' / 'partials' / '_code_window.html'


def _post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type='application/json')


class CodeWindowTestBase(TestCase):
    """A Python write-code exercise plus one user per role that matters."""

    @classmethod
    def setUpTestData(cls):
        for role_name in (Role.STUDENT, Role.TEACHER, Role.PARENT):
            Role.objects.get_or_create(
                name=role_name, defaults={'display_name': role_name.title()},
            )

        cls.student = CustomUser.objects.create_user(
            'cw_student', 'cw_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.student.roles.add(Role.objects.get(name=Role.STUDENT))

        cls.teacher = CustomUser.objects.create_user(
            'cw_teacher', 'cw_teacher@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.teacher.roles.add(Role.objects.get(name=Role.TEACHER))

        cls.parent = CustomUser.objects.create_user(
            'cw_parent', 'cw_parent@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.parent.roles.add(Role.objects.get(name=Role.PARENT))

        cls.python = CodingLanguage.objects.create(
            name='Python', slug=CodingLanguage.PYTHON, order=1, is_active=True,
        )
        cls.html = CodingLanguage.objects.create(
            name='HTML', slug=CodingLanguage.HTML, order=2, is_active=True,
        )
        cls.scratch = CodingLanguage.objects.create(
            name='Scratch', slug=CodingLanguage.SCRATCH, order=3, is_active=True,
        )

        cls.exercise = cls._make_exercise(
            cls.python, 'Print a greeting',
            starter='print("hi")\n', expected='hi', solution='print("hi")\n',
        )

    @classmethod
    def _make_exercise(cls, language, title, starter='', expected='', solution='',
                       question_type=CodingExercise.WRITE_CODE):
        topic = CodingTopic.objects.create(
            language=language, name=f'{title} topic',
            slug=f'{language.slug}-{title.lower().replace(" ", "-")}',
            order=1, is_active=True,
        )
        topic_level, _ = TopicLevel.get_or_create_for(topic, TopicLevel.BEGINNER)
        return CodingExercise.objects.create(
            topic_level=topic_level, title=title, description='Do the thing.',
            starter_code=starter, expected_output=expected, solution_code=solution,
            question_type=question_type, is_active=True,
        )


# ---------------------------------------------------------------------------
# window_context_for_exercise
# ---------------------------------------------------------------------------

class TestWindowContext(CodeWindowTestBase):

    def _context(self, exercise=None):
        return window_context_for_exercise(exercise or self.exercise, '/coding/api/preview-run/')

    def test_python_exercise_runs_in_console_mode(self):
        ctx = self._context()
        self.assertEqual(ctx['cw_mode'], 'run')
        self.assertEqual(ctx['cw_cm_mode'], 'python')
        self.assertEqual(ctx['cw_filename'], 'main.py')
        self.assertEqual(ctx['cw_starter'], 'print("hi")\n')
        self.assertEqual(ctx['cw_expected_output'], 'hi')

    def test_html_exercise_renders_as_a_preview(self):
        exercise = self._make_exercise(self.html, 'Build a page', starter='<h1>Hi</h1>')
        ctx = self._context(exercise)
        self.assertEqual(ctx['cw_mode'], 'preview')
        self.assertEqual(ctx['cw_starter_html'], '<h1>Hi</h1>')
        # Nothing runs, so there is no output to compare against.
        self.assertEqual(ctx['cw_expected_output'], '')

    def test_browser_sandbox_exercise_overrides_its_language(self):
        """A DOM exercise filed under Python still renders in the browser."""
        exercise = self._make_exercise(self.python, 'DOM task', starter='<p>x</p>')
        exercise.uses_browser_sandbox = True
        exercise.save()
        ctx = self._context(exercise)
        self.assertEqual(ctx['cw_mode'], 'preview')
        self.assertEqual(ctx['cw_starter_html'], '<p>x</p>')

    def test_scratch_exercise_has_no_window(self):
        """Scratch is block-based — a text editor would misrepresent it."""
        exercise = self._make_exercise(self.scratch, 'Move the cat')
        self.assertFalse(supports_code_window(exercise))
        self.assertIsNone(self._context(exercise))

    def test_quiz_exercise_has_no_window(self):
        exercise = self._make_exercise(
            self.python, 'Which is a list?',
            question_type=CodingExercise.MULTIPLE_CHOICE,
        )
        self.assertFalse(supports_code_window(exercise))
        self.assertIsNone(self._context(exercise))


# ---------------------------------------------------------------------------
# The partials
# ---------------------------------------------------------------------------

class TestCodeWindowPartial(CodeWindowTestBase):

    def _render(self, **overrides):
        context = {
            'cw_id': 'test',
            'cw_run_url': '/coding/api/preview-run/',
            'csrf_token': 'tok',
            **(window_context_for_exercise(self.exercise, '/coding/api/preview-run/')),
        }
        context.update(overrides)
        return render_to_string('coding/partials/_code_window.html', context)

    def test_config_block_is_valid_json(self):
        """The mount reads this blob — a broken one leaves a dead editor."""
        html = self._render()
        blob = re.search(
            r'<script type="application/json" class="cw-config">(.*?)</script>',
            html, re.S,
        )
        self.assertIsNotNone(blob, 'config script tag missing')
        config = json.loads(blob.group(1))
        self.assertEqual(config['mode'], 'run')
        self.assertEqual(config['language'], 'python')
        self.assertEqual(config['starter'], 'print("hi")\n')
        self.assertEqual(config['expectedOutput'], 'hi')

    def test_config_json_survives_code_containing_quotes_and_newlines(self):
        """Starter code is arbitrary text; it must not break out of the JSON."""
        nasty = 'print("a\\nb")  # </script><script>alert(1)</script>\n\'quoted\'\n'
        html = self._render(cw_starter=nasty)
        blob = re.search(
            r'<script type="application/json" class="cw-config">(.*?)</script>',
            html, re.S,
        )
        config = json.loads(blob.group(1))
        self.assertEqual(config['starter'], nasty)
        # The closing tag inside the code must not appear literally, or the
        # browser would end the script element early.
        self.assertNotIn('</script><script>alert(1)', html)

    def test_window_has_editor_and_console(self):
        html = self._render()
        self.assertIn('cw-editor', html)
        self.assertIn('cw-stdout', html)
        self.assertIn('cw-run', html)

    def test_preview_mode_swaps_the_console_for_an_iframe(self):
        exercise = self._make_exercise(self.html, 'Page', starter='<h1>Hi</h1>')
        html = self._render(
            **window_context_for_exercise(exercise, '/coding/api/preview-run/'))
        self.assertIn('cw-preview', html)
        self.assertNotIn('cw-stdout', html)

    def test_no_template_comment_leaks_into_the_page(self):
        """Django's {# … #} is single-line; a multi-line one renders as text."""
        for html in (self._render(), self._render(cw_extra_code='x')):
            for leak in ('{#', '#}', '{%'):
                self.assertNotIn(leak, html, f'unrendered template syntax {leak!r}')

    def test_load_solution_button_only_when_a_solution_is_passed(self):
        self.assertNotIn('cw-load', self._render())
        self.assertIn('cw-load', self._render(cw_extra_code='print("hi")'))


class TestCodeWindowAssetsAreSelfHosted(TestCase):
    """The window must not depend on a third-party CDN to work.

    The worksheet builder loads this partial, and the builder has already been
    killed once by a CDN fetch that failed (SortableJS). CodeMirror is vendored
    under static/vendor/codemirror/ — this test is what keeps it that way.
    """

    def test_head_partial_references_no_cdn(self):
        source = HEAD_PARTIAL.read_text(encoding='utf-8')
        urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', source)
        self.assertEqual(urls, [], f'CDN reference in {HEAD_PARTIAL.name}: {urls}')

    def test_no_coding_template_references_the_codemirror_cdn(self):
        """Every coding page serves its editor from static/, not cdnjs.

        Each page used to paste the CodeMirror script tags into its own head.
        They all include _code_window_head.html now — this is what stops a new
        page (or a revert) quietly reintroducing the CDN dependency.
        """
        offenders = [
            path.relative_to(TEMPLATES_DIR)
            for path in (TEMPLATES_DIR / 'coding').rglob('*.html')
            if 'cdnjs.cloudflare.com/ajax/libs/codemirror' in path.read_text(encoding='utf-8')
        ]
        self.assertEqual(offenders, [], f'CodeMirror loaded from a CDN in: {offenders}')

    def test_vendored_codemirror_files_exist(self):
        vendor = Path(settings.BASE_DIR) / 'static' / 'vendor' / 'codemirror'
        for rel in (
            'codemirror.min.js', 'codemirror.min.css', 'theme/dracula.min.css',
            'mode/python/python.min.js', 'mode/javascript/javascript.min.js',
            'mode/xml/xml.min.js', 'mode/css/css.min.js',
            'mode/htmlmixed/htmlmixed.min.js',
            'addon/edit/matchbrackets.min.js', 'addon/edit/closebrackets.min.js',
            'addon/selection/active-line.min.js',
            'addon/hint/show-hint.min.js', 'addon/hint/show-hint.min.css',
            'addon/hint/anyword-hint.min.js',
        ):
            self.assertTrue((vendor / rel).is_file(), f'missing vendored asset: {rel}')


# ---------------------------------------------------------------------------
# api_preview_run
# ---------------------------------------------------------------------------

class TestApiPreviewRun(CodeWindowTestBase):

    def setUp(self):
        self.url = reverse('coding:api_preview_run')
        self.client.force_login(self.teacher)

    # --- Access control ---

    def test_requires_login(self):
        resp = _post(Client(), self.url, {'language': 'python', 'code': 'x=1'})
        self.assertEqual(resp.status_code, 302)

    def test_student_is_redirected(self):
        """Students run code through api_run_code, which scores their work."""
        self.client.force_login(self.student)
        resp = _post(self.client, self.url, {'language': 'python', 'code': 'x=1'})
        self.assertEqual(resp.status_code, 302)

    def test_parent_is_redirected(self):
        self.client.force_login(self.parent)
        resp = _post(self.client, self.url, {'language': 'python', 'code': 'x=1'})
        self.assertEqual(resp.status_code, 302)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    # --- Validation ---

    def test_invalid_json_returns_400(self):
        resp = self.client.post(self.url, data='not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_language_returns_400(self):
        resp = _post(self.client, self.url, {'code': 'print(1)'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_code_returns_400(self):
        resp = _post(self.client, self.url, {'language': 'python'})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_language_returns_400(self):
        resp = _post(self.client, self.url, {'language': 'cobol', 'code': 'x'})
        self.assertEqual(resp.status_code, 400)

    def test_browser_language_is_rejected_rather_than_silently_empty(self):
        resp = _post(self.client, self.url, {'language': 'html', 'code': '<h1>x</h1>'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('browser', resp.json()['error'])

    # --- Happy path ---

    def test_runs_code_and_returns_output(self):
        with patch('coding.execution.run_code',
                   return_value={'stdout': 'hi\n', 'stderr': '', 'exit_code': 0}) as run:
            resp = _post(self.client, self.url,
                         {'language': 'python', 'code': 'print("hi")', 'stdin': '2\n'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['stdout'], 'hi\n')
        run.assert_called_once_with('python', 'print("hi")', '2\n')

    def test_accepts_language_slug_alias(self):
        with patch('coding.execution.run_code',
                   return_value={'stdout': '', 'stderr': '', 'exit_code': 0}):
            resp = _post(self.client, self.url,
                         {'language_slug': 'python', 'code': 'pass'})
        self.assertEqual(resp.status_code, 200)

    def test_records_nothing_against_the_teacher(self):
        """The whole point: a teacher trying an exercise leaves no trace.

        student_required keeps teachers off api_run_code precisely so they do
        not accumulate submissions and time logs. This endpoint gives them the
        editor back without giving that up.
        """
        with patch('coding.execution.run_code',
                   return_value={'stdout': 'hi\n', 'stderr': '', 'exit_code': 0}):
            _post(self.client, self.url,
                  {'language': 'python', 'code': 'print("hi")',
                   'exercise_id': self.exercise.pk, 'mark_complete': True})

        self.assertEqual(StudentExerciseSubmission.objects.count(), 0)
        self.assertEqual(CodingTimeLog.objects.count(), 0)
