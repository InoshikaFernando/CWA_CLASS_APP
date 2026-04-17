"""
test_dom_exercise.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for the JavaScript DOM exercise implementation.

Feature under test:
  CodingExercise.uses_browser_sandbox (BooleanField, default=False)

  When an exercise has uses_browser_sandbox=True the platform must:
    1. Return {'browser_sandbox': True} from api_run_code — never call Piston.
    2. Save a completed StudentExerciseSubmission when mark_complete=True.
    3. Render the exercise_detail page with the correct context flag.
    4. Render an iframe preview panel instead of a Node.js output panel.

  Regular JavaScript exercises (uses_browser_sandbox=False) must be unaffected:
    5. They still go to Piston.
    6. Their exercise_detail page still shows the output panel.

  Covered sections
  ----------------
  A  Model field — default, persistence, independence from language flag
  B  api_run_code routing — DOM vs algorithm JS vs HTML/CSS
  C  api_run_code + mark_complete — submission saved / not saved
  D  exercise_detail GET — context, template content
  E  Seed helper — uses_browser_sandbox written by seed_coding.py seeder
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingTopic,
    TopicLevel,
    StudentExerciseSubmission,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PISTON_OK = {'stdout': 'hello', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05}


def _lang(slug, name, order=1):
    lang, _ = CodingLanguage.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'color': '#000', 'order': order,
                  'is_active': True, 'description': f'{name} lang'},
    )
    return lang


def _topic(lang, name, slug):
    t, _ = CodingTopic.objects.get_or_create(
        language=lang, slug=slug,
        defaults={'name': name, 'order': 1, 'is_active': True},
    )
    return t


def _exercise(topic, title, level=CodingExercise.BEGINNER,
              starter='// code', uses_browser_sandbox=False):
    tl, _ = TopicLevel.get_or_create_for(topic, level)
    return CodingExercise.objects.create(
        topic_level=tl,
        title=title,
        description=f'Instructions for {title}.',
        starter_code=starter,
        order=1,
        is_active=True,
        uses_browser_sandbox=uses_browser_sandbox,
    )


def _post(client, payload):
    return client.post(
        reverse('coding:api_run_code'),
        data=json.dumps(payload),
        content_type='application/json',
    )


def _detail_url(lang_slug, exercise_id):
    return reverse('coding:exercise_detail', args=[lang_slug, exercise_id])


# ===========================================================================
# A  Model field
# ===========================================================================

class TestExerciseUsesBrowserSandboxField(TestCase):
    """
    CodingExercise.uses_browser_sandbox is a BooleanField(default=False).
    It is independent of the language-level uses_browser_sandbox property.
    """

    @classmethod
    def setUpTestData(cls):
        cls.js_lang = _lang('javascript', 'JavaScript', order=2)
        cls.js_topic = _topic(cls.js_lang, 'DOM Basics', 'dom-basics-model')

    def test_default_is_false(self):
        """An exercise created without the flag defaults to False."""
        ex = _exercise(self.js_topic, 'No Flag Exercise')
        self.assertFalse(ex.uses_browser_sandbox)

    def test_can_be_set_true_for_javascript_exercise(self):
        """uses_browser_sandbox=True persists for a JavaScript-language exercise."""
        ex = _exercise(self.js_topic, 'DOM Exercise', uses_browser_sandbox=True)
        ex.refresh_from_db()
        self.assertTrue(ex.uses_browser_sandbox)

    def test_language_flag_unaffected_by_exercise_flag(self):
        """
        Setting uses_browser_sandbox on an exercise must NOT change the language
        CodingLanguage.uses_browser_sandbox property (which is Python-computed).
        """
        ex = _exercise(self.js_topic, 'DOM Flag Independence', uses_browser_sandbox=True)
        self.assertFalse(ex.topic_level.topic.language.uses_browser_sandbox)

    def test_algorithm_exercise_has_false_flag(self):
        """A regular JS algorithm exercise must have uses_browser_sandbox=False."""
        ex = _exercise(self.js_topic, 'Algorithm Exercise', uses_browser_sandbox=False)
        self.assertFalse(ex.uses_browser_sandbox)

    def test_can_update_flag_via_save(self):
        """The flag can be toggled after creation."""
        ex = _exercise(self.js_topic, 'Toggle Exercise', uses_browser_sandbox=False)
        ex.uses_browser_sandbox = True
        ex.save(update_fields=['uses_browser_sandbox'])
        ex.refresh_from_db()
        self.assertTrue(ex.uses_browser_sandbox)

    def test_multiple_exercises_independent_flags(self):
        """Each exercise carries its own flag; one True must not affect another False."""
        dom_ex = _exercise(self.js_topic, 'DOM Multi', uses_browser_sandbox=True)
        algo_ex = _exercise(self.js_topic, 'Algo Multi', uses_browser_sandbox=False)
        dom_ex.refresh_from_db()
        algo_ex.refresh_from_db()
        self.assertTrue(dom_ex.uses_browser_sandbox)
        self.assertFalse(algo_ex.uses_browser_sandbox)

    def test_html_language_exercise_also_supports_field(self):
        """The field exists on exercises of any language, not only JavaScript."""
        html_lang = _lang('html', 'HTML', order=3)
        html_topic = _topic(html_lang, 'Structure', 'html-struct-model')
        ex = _exercise(html_topic, 'HTML Exercise', uses_browser_sandbox=False)
        self.assertFalse(ex.uses_browser_sandbox)


# ===========================================================================
# B  api_run_code routing
# ===========================================================================

class TestApiRunCodeDomRouting(TestCase):
    """
    POST /coding/api/run/

    DOM exercises (uses_browser_sandbox=True on the exercise) must return
    {'browser_sandbox': True} and never call Piston.

    Algorithm JS exercises must still reach Piston.
    HTML/CSS exercises route via the language flag (unchanged).
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='dom_run_student', password='pass',
            email='dom_run_student@test.com',
        )
        cls.js_lang = _lang('javascript', 'JavaScript', order=2)
        cls.html_lang = _lang('html', 'HTML', order=3)

        js_topic = _topic(cls.js_lang, 'DOM Basics', 'dom-basics-run')
        html_topic = _topic(cls.html_lang, 'Structure', 'html-struct-run')

        cls.dom_exercise = _exercise(
            js_topic, 'Event Listener',
            starter='<!DOCTYPE html><html><body><button id="btn">Click</button>'
                    '<script>document.getElementById("btn").addEventListener'
                    '("click",function(){alert("clicked");});</script></body></html>',
            uses_browser_sandbox=True,
        )
        cls.algo_exercise = _exercise(
            js_topic, 'Reverse String',
            starter='const s = "hello"; console.log(s.split("").reverse().join(""));',
            uses_browser_sandbox=False,
        )
        cls.html_exercise = _exercise(
            html_topic, 'My First Page',
            starter='<!DOCTYPE html><html><body><h1>Hello</h1></body></html>',
            uses_browser_sandbox=False,  # language flag handles HTML
        )

    def setUp(self):
        self.client.force_login(self.student)

    # ── DOM exercise → browser sandbox, never Piston ─────────────────────────

    def test_dom_exercise_returns_browser_sandbox_flag(self):
        """A JS exercise with uses_browser_sandbox=True must return browser_sandbox:True."""
        resp = _post(self.client, {
            'language_slug': 'javascript',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.dom_exercise.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('browser_sandbox'))

    def test_dom_exercise_never_calls_piston(self):
        """Piston (run_code) must NOT be called for a DOM exercise."""
        with patch('coding.execution.run_code') as mock_rc:
            _post(self.client, {
                'language_slug': 'javascript',
                'code': '<!DOCTYPE html><html></html>',
                'exercise_id': self.dom_exercise.id,
            })
        mock_rc.assert_not_called()

    def test_dom_exercise_response_has_no_stdout(self):
        """Browser-sandbox responses carry no stdout/stderr — just the flag."""
        resp = _post(self.client, {
            'language_slug': 'javascript',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.dom_exercise.id,
        })
        data = resp.json()
        self.assertNotIn('stdout', data)
        self.assertNotIn('stderr', data)
        self.assertNotIn('error', data)

    # ── Algorithm JS exercise → Piston ───────────────────────────────────────

    def test_algorithm_exercise_calls_piston(self):
        """A regular JS exercise (uses_browser_sandbox=False) must reach Piston."""
        with patch('coding.execution.run_code', return_value=_PISTON_OK) as mock_rc:
            resp = _post(self.client, {
                'language_slug': 'javascript',
                'code': 'console.log("hello")',
                'exercise_id': self.algo_exercise.id,
            })
        self.assertEqual(resp.status_code, 200)
        mock_rc.assert_called_once()

    def test_algorithm_exercise_returns_stdout(self):
        """Piston stdout must be forwarded in the response for algorithm exercises."""
        with patch('coding.execution.run_code', return_value=_PISTON_OK):
            resp = _post(self.client, {
                'language_slug': 'javascript',
                'code': 'console.log("hello")',
                'exercise_id': self.algo_exercise.id,
            })
        self.assertEqual(resp.json()['stdout'], 'hello')

    def test_algorithm_exercise_does_not_return_browser_sandbox_flag(self):
        """An algorithm JS exercise must NOT return browser_sandbox=True."""
        with patch('coding.execution.run_code', return_value=_PISTON_OK):
            resp = _post(self.client, {
                'language_slug': 'javascript',
                'code': 'console.log("hello")',
                'exercise_id': self.algo_exercise.id,
            })
        self.assertFalse(resp.json().get('browser_sandbox', False))

    # ── HTML/CSS — language-level sandbox (unchanged) ────────────────────────

    def test_html_language_returns_browser_sandbox_flag(self):
        """HTML language uses_browser_sandbox=True → browser_sandbox:True regardless of exercise flag."""
        resp = _post(self.client, {
            'language_slug': 'html',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.html_exercise.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('browser_sandbox'))

    # ── No exercise_id — falls back to language-level only ───────────────────

    def test_js_without_exercise_id_calls_piston(self):
        """Without an exercise_id the JS language routes normally to Piston."""
        with patch('coding.execution.run_code', return_value=_PISTON_OK) as mock_rc:
            resp = _post(self.client, {
                'language_slug': 'javascript',
                'code': 'console.log("hi")',
            })
        self.assertEqual(resp.status_code, 200)
        mock_rc.assert_called_once()

    def test_invalid_exercise_id_falls_back_to_language_routing(self):
        """A nonexistent exercise_id must not crash — JS still routes to Piston."""
        with patch('coding.execution.run_code', return_value=_PISTON_OK):
            resp = _post(self.client, {
                'language_slug': 'javascript',
                'code': 'console.log("hi")',
                'exercise_id': 999999,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('stdout', resp.json())


# ===========================================================================
# C  api_run_code + mark_complete → submission persistence
# ===========================================================================

class TestApiRunCodeDomMarkComplete(TestCase):
    """
    When mark_complete=True is sent with a DOM exercise the view must save
    a completed StudentExerciseSubmission.
    When mark_complete is absent or False no submission must be created.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='dom_mark_student', password='pass',
            email='dom_mark_student@test.com',
        )
        cls.js_lang = _lang('javascript', 'JavaScript', order=2)
        js_topic = _topic(cls.js_lang, 'DOM Mark', 'dom-basics-mark')
        cls.dom_ex = _exercise(js_topic, 'Click Counter', uses_browser_sandbox=True)
        cls.algo_ex = _exercise(js_topic, 'Sum Array', uses_browser_sandbox=False)

    def setUp(self):
        self.client.force_login(self.student)

    def _run(self, payload):
        return _post(self.client, payload)

    # ── DOM exercise submissions ──────────────────────────────────────────────

    def test_mark_complete_true_creates_submission_for_dom_exercise(self):
        """mark_complete=True on a DOM exercise must persist a completed submission."""
        self._run({
            'language_slug': 'javascript',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.dom_ex.id,
            'mark_complete': True,
        })
        sub = StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=self.dom_ex,
        ).first()
        self.assertIsNotNone(sub)
        self.assertTrue(sub.is_completed)

    def test_mark_complete_false_does_not_create_submission(self):
        """mark_complete=False must NOT persist any submission."""
        self._run({
            'language_slug': 'javascript',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.dom_ex.id,
            'mark_complete': False,
        })
        count = StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=self.dom_ex,
        ).count()
        self.assertEqual(count, 0)

    def test_mark_complete_absent_does_not_create_submission(self):
        """Omitting mark_complete must not create a submission."""
        self._run({
            'language_slug': 'javascript',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.dom_ex.id,
        })
        count = StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=self.dom_ex,
        ).count()
        self.assertEqual(count, 0)

    def test_submission_stores_code_for_dom_exercise(self):
        """The saved submission must store the submitted code verbatim."""
        html_code = '<!DOCTYPE html><html><body><p>Hello</p></body></html>'
        self._run({
            'language_slug': 'javascript',
            'code': html_code,
            'exercise_id': self.dom_ex.id,
            'mark_complete': True,
        })
        sub = StudentExerciseSubmission.objects.get(
            student=self.student, exercise=self.dom_ex,
        )
        self.assertEqual(sub.code_submitted, html_code)

    def test_repeated_mark_complete_upserts_submission(self):
        """Calling mark_complete twice must update the existing submission, not duplicate it."""
        for _ in range(2):
            self._run({
                'language_slug': 'javascript',
                'code': '<!DOCTYPE html><html></html>',
                'exercise_id': self.dom_ex.id,
                'mark_complete': True,
            })
        count = StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=self.dom_ex,
        ).count()
        self.assertEqual(count, 1)

    def test_student_isolation_for_dom_submission(self):
        """Completing a DOM exercise for student A must not affect student B."""
        student_b = User.objects.create_user(
            username='dom_mark_b', password='pass', email='dom_mark_b@test.com',
        )
        self._run({
            'language_slug': 'javascript',
            'code': '<!DOCTYPE html><html></html>',
            'exercise_id': self.dom_ex.id,
            'mark_complete': True,
        })
        # Student B has no submission
        count_b = StudentExerciseSubmission.objects.filter(
            student=student_b, exercise=self.dom_ex,
        ).count()
        self.assertEqual(count_b, 0)

    # ── Algorithm exercise submissions (unchanged behaviour) ──────────────────

    def test_algorithm_exercise_submission_saved_on_mark_complete(self):
        """Algorithm exercises still create submissions via Piston path."""
        with patch('coding.execution.run_code', return_value=_PISTON_OK):
            self._run({
                'language_slug': 'javascript',
                'code': 'console.log("hi")',
                'exercise_id': self.algo_ex.id,
                'mark_complete': True,
            })
        sub = StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=self.algo_ex,
        ).first()
        self.assertIsNotNone(sub)
        self.assertTrue(sub.is_completed)


# ===========================================================================
# D  exercise_detail GET — context and template rendering
# ===========================================================================

class TestExerciseDetailDomContext(TestCase):
    """
    GET /coding/<lang>/exercise/<id>/

    For a DOM exercise (uses_browser_sandbox=True on the exercise):
      - Page loads with 200
      - exercise.uses_browser_sandbox is True in template context
      - Live preview iframe is rendered (sandbox="allow-scripts allow-modals")
      - Node.js output panel is NOT rendered
      - File label reads 'index.html', not 'main.js'

    For a regular JS exercise (uses_browser_sandbox=False):
      - exercise.uses_browser_sandbox is False
      - Node.js output panel IS rendered
      - No live preview iframe
      - File label reads 'main.js'
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='dom_detail_student', password='pass',
            email='dom_detail_student@test.com',
        )
        cls.js_lang = _lang('javascript', 'JavaScript', order=2)
        js_topic = _topic(cls.js_lang, 'DOM Basics', 'dom-basics-detail')

        cls.dom_ex = _exercise(
            js_topic, 'Add CSS Class',
            starter=(
                '<!DOCTYPE html>\n<html>\n<body>\n'
                '  <div id="text">Hello</div>\n'
                '  <script>document.getElementById("text").classList.add("highlight");</script>\n'
                '</body>\n</html>'
            ),
            uses_browser_sandbox=True,
        )
        cls.algo_ex = _exercise(
            js_topic, 'Reverse String',
            starter='const s="hello"; console.log(s.split("").reverse().join(""));',
            uses_browser_sandbox=False,
        )

    def setUp(self):
        self.client.force_login(self.student)
        self.dom_resp  = self.client.get(_detail_url('javascript', self.dom_ex.id))
        self.algo_resp = self.client.get(_detail_url('javascript', self.algo_ex.id))

    # ── Basic response ────────────────────────────────────────────────────────

    def test_dom_exercise_returns_200(self):
        self.assertEqual(self.dom_resp.status_code, 200)

    def test_algo_exercise_returns_200(self):
        self.assertEqual(self.algo_resp.status_code, 200)

    # ── Context flag ──────────────────────────────────────────────────────────

    def test_dom_exercise_has_browser_sandbox_flag_true_in_context(self):
        """exercise.uses_browser_sandbox must be True in the template context."""
        self.assertTrue(self.dom_resp.context['exercise'].uses_browser_sandbox)

    def test_algo_exercise_has_browser_sandbox_flag_false_in_context(self):
        """Algorithm exercise must NOT have the flag set."""
        self.assertFalse(self.algo_resp.context['exercise'].uses_browser_sandbox)

    def test_language_uses_browser_sandbox_false_for_js(self):
        """JavaScript language-level flag must remain False for both exercise types."""
        self.assertFalse(self.dom_resp.context['language'].uses_browser_sandbox)
        self.assertFalse(self.algo_resp.context['language'].uses_browser_sandbox)

    # ── Template content: iframe preview ─────────────────────────────────────

    def test_dom_exercise_renders_iframe_preview(self):
        """DOM exercise must render the sandboxed iframe preview panel."""
        self.assertContains(self.dom_resp, 'id="ed-preview-frame"')

    def test_dom_exercise_iframe_has_allow_scripts(self):
        """The preview iframe must include allow-scripts in the sandbox attribute."""
        self.assertContains(self.dom_resp, 'allow-scripts')

    def test_dom_exercise_iframe_has_allow_modals(self):
        """
        The preview iframe must include allow-modals so that alert()/confirm()
        work inside DOM exercises (e.g. the Event Listener exercise).
        """
        self.assertContains(self.dom_resp, 'allow-modals')

    def test_algo_exercise_does_not_render_iframe_preview(self):
        """Algorithm JS exercise must NOT render the iframe preview panel."""
        self.assertNotContains(self.algo_resp, 'id="ed-preview-frame"')

    # ── Template content: output panel ───────────────────────────────────────

    def test_algo_exercise_renders_output_panel(self):
        """Algorithm JS exercise must render the Node.js output panel."""
        self.assertContains(self.algo_resp, 'id="ed-stdout"')

    def test_dom_exercise_does_not_render_output_panel(self):
        """DOM exercise must NOT render the Node.js output panel."""
        self.assertNotContains(self.dom_resp, 'id="ed-stdout"')

    # ── Template content: file label ─────────────────────────────────────────

    def test_dom_exercise_editor_shows_index_html(self):
        """DOM exercises write full HTML — the file label must read 'index.html'."""
        self.assertContains(self.dom_resp, 'index.html')

    def test_algo_exercise_editor_shows_main_js(self):
        """Algorithm JS exercises use Node.js — the file label must read 'main.js'."""
        self.assertContains(self.algo_resp, 'main.js')

    # ── IS_BROWSER JavaScript constant ───────────────────────────────────────

    def test_dom_exercise_sets_is_browser_true_in_js(self):
        """
        The inline JS constant IS_BROWSER must be true for DOM exercises so
        that edRun() renders in the iframe instead of calling the server.
        """
        content = self.dom_resp.content.decode()
        # The template renders: IS_BROWSER = ... || true;
        # so we look for 'true' appearing after 'IS_BROWSER'
        idx_is_browser = content.find('IS_BROWSER')
        self.assertGreater(idx_is_browser, 0)
        # Grab the line that sets IS_BROWSER
        line_start = content.rfind('\n', 0, idx_is_browser)
        line_end   = content.find('\n', idx_is_browser)
        is_browser_line = content[line_start:line_end]
        self.assertIn('true', is_browser_line)

    def test_algo_exercise_sets_is_browser_false_in_js(self):
        """IS_BROWSER must be false for algorithm JS exercises."""
        content = self.algo_resp.content.decode()
        idx_is_browser = content.find('IS_BROWSER')
        self.assertGreater(idx_is_browser, 0)
        line_start = content.rfind('\n', 0, idx_is_browser)
        line_end   = content.find('\n', idx_is_browser)
        is_browser_line = content[line_start:line_end]
        self.assertIn('false', is_browser_line)

    # ── Completion state ──────────────────────────────────────────────────────

    def test_dom_exercise_is_completed_false_initially(self):
        self.assertFalse(self.dom_resp.context['is_completed'])

    def test_dom_exercise_is_completed_true_after_submission(self):
        StudentExerciseSubmission.objects.create(
            student=self.student, exercise=self.dom_ex,
            code_submitted='<!DOCTYPE html><html></html>',
            is_completed=True,
        )
        resp = self.client.get(_detail_url('javascript', self.dom_ex.id))
        self.assertTrue(resp.context['is_completed'])

    def test_incomplete_submission_does_not_set_is_completed(self):
        StudentExerciseSubmission.objects.create(
            student=self.student, exercise=self.dom_ex,
            code_submitted='<!-- wip -->', is_completed=False,
        )
        resp = self.client.get(_detail_url('javascript', self.dom_ex.id))
        self.assertFalse(resp.context['is_completed'])


# ===========================================================================
# E  Seed helper — uses_browser_sandbox written by seed_coding.py
# ===========================================================================

class TestSeedCodingUsesBrowserSandbox(TestCase):
    """
    The seed_coding management command reads uses_browser_sandbox from the
    JSON exercise definition and stores it on the CodingExercise record.

    This test simulates the seeder's update_or_create call directly to
    verify the field is correctly propagated without running the full command.
    """

    @classmethod
    def setUpTestData(cls):
        cls.js_lang = _lang('javascript', 'JavaScript', order=2)
        cls.js_topic = _topic(cls.js_lang, 'DOM Basics', 'dom-basics-seed')

    def _seed_exercise(self, title, uses_browser_sandbox):
        """Simulate what seed_coding.py does for a single exercise entry."""
        tl, _ = TopicLevel.get_or_create_for(self.js_topic, CodingExercise.BEGINNER)
        ex_data = {
            'instructions': f'Do {title}',
            'starter_code': '<!DOCTYPE html>',
            'expected_output': '',
            'hints': '',
            'display_order': 1,
            'uses_browser_sandbox': uses_browser_sandbox,
        }
        obj, created = CodingExercise.objects.update_or_create(
            topic_level=tl,
            title=title,
            defaults={
                'description':          ex_data.get('instructions', ''),
                'starter_code':         ex_data.get('starter_code', ''),
                'expected_output':      ex_data.get('expected_output', ''),
                'hints':                ex_data.get('hints', ''),
                'order':                ex_data.get('display_order', 0),
                'uses_browser_sandbox': ex_data.get('uses_browser_sandbox', False),
                'is_active':            True,
            },
        )
        return obj, created

    def test_seed_creates_dom_exercise_with_flag_true(self):
        """Seeder must persist uses_browser_sandbox=True when JSON has true."""
        ex, created = self._seed_exercise('Seed DOM Exercise', uses_browser_sandbox=True)
        self.assertTrue(created)
        ex.refresh_from_db()
        self.assertTrue(ex.uses_browser_sandbox)

    def test_seed_creates_algorithm_exercise_with_flag_false(self):
        """Seeder must persist uses_browser_sandbox=False when JSON has false."""
        ex, created = self._seed_exercise('Seed Algo Exercise', uses_browser_sandbox=False)
        self.assertTrue(created)
        ex.refresh_from_db()
        self.assertFalse(ex.uses_browser_sandbox)

    def test_seed_updates_existing_exercise_flag(self):
        """
        Re-seeding an existing exercise must update uses_browser_sandbox
        (update_or_create with flag in defaults).
        """
        # First seed: False
        ex, _ = self._seed_exercise('Seed Update Exercise', uses_browser_sandbox=False)
        self.assertFalse(ex.uses_browser_sandbox)
        # Re-seed: True
        ex2, created = self._seed_exercise('Seed Update Exercise', uses_browser_sandbox=True)
        self.assertFalse(created)           # should update, not create
        ex2.refresh_from_db()
        self.assertTrue(ex2.uses_browser_sandbox)

    def test_seed_missing_flag_defaults_to_false(self):
        """
        If the JSON entry omits uses_browser_sandbox the seeder must default to False
        via ex_data.get('uses_browser_sandbox', False).
        """
        tl, _ = TopicLevel.get_or_create_for(self.js_topic, CodingExercise.INTERMEDIATE)
        ex_data = {
            'instructions': 'Omitted flag exercise',
            'starter_code': '// code',
            'expected_output': '',
            'hints': '',
            'display_order': 1,
            # 'uses_browser_sandbox' intentionally absent
        }
        obj, _ = CodingExercise.objects.update_or_create(
            topic_level=tl,
            title='Seed Missing Flag Exercise',
            defaults={
                'description':          ex_data.get('instructions', ''),
                'starter_code':         ex_data.get('starter_code', ''),
                'expected_output':      ex_data.get('expected_output', ''),
                'hints':                ex_data.get('hints', ''),
                'order':                ex_data.get('display_order', 0),
                'uses_browser_sandbox': ex_data.get('uses_browser_sandbox', False),
                'is_active':            True,
            },
        )
        obj.refresh_from_db()
        self.assertFalse(obj.uses_browser_sandbox)


# ===========================================================================
# F  Regression: existing language routes are not broken
# ===========================================================================

class TestDomFeatureRegression(TestCase):
    """
    Confirm that adding exercise-level uses_browser_sandbox does not
    accidentally break existing language routing for Python, HTML, CSS, Scratch.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='dom_regress_student', password='pass',
            email='dom_regress_student@test.com',
        )
        cls.py_lang   = _lang('python',     'Python',     order=1)
        cls.html_lang = _lang('html',       'HTML',       order=3)
        cls.css_lang  = _lang('css',        'CSS',        order=4)
        cls.sc_lang   = _lang('scratch',    'Scratch',    order=5)

        py_t   = _topic(cls.py_lang,   'Vars',    'py-vars-reg')
        html_t = _topic(cls.html_lang, 'Struct',  'html-struct-reg')
        css_t  = _topic(cls.css_lang,  'Basics',  'css-basics-reg')
        sc_t   = _topic(cls.sc_lang,   'Motion',  'sc-motion-reg')

        cls.py_ex   = _exercise(py_t,   'Python Reg',  starter='print("hi")')
        cls.html_ex = _exercise(html_t, 'HTML Reg',    starter='<html></html>')
        cls.css_ex  = _exercise(css_t,  'CSS Reg',     starter='body { color: red; }')
        cls.sc_ex   = _exercise(sc_t,   'Scratch Reg', starter='<xml></xml>')

    def setUp(self):
        self.client.force_login(self.student)

    def test_python_exercise_uses_browser_sandbox_false(self):
        self.assertFalse(self.py_ex.uses_browser_sandbox)

    def test_python_exercise_page_loads(self):
        resp = self.client.get(_detail_url('python', self.py_ex.id))
        self.assertEqual(resp.status_code, 200)

    def test_python_api_run_calls_piston(self):
        with patch('coding.execution.run_code', return_value=_PISTON_OK) as mock_rc:
            _post(self.client, {
                'language_slug': 'python',
                'code': 'print("hi")',
                'exercise_id': self.py_ex.id,
            })
        mock_rc.assert_called_once()

    def test_html_exercise_page_loads(self):
        resp = self.client.get(_detail_url('html', self.html_ex.id))
        self.assertEqual(resp.status_code, 200)

    def test_html_api_run_returns_browser_sandbox(self):
        """HTML language still routes to browser sandbox via language-level flag."""
        resp = _post(self.client, {
            'language_slug': 'html',
            'code': '<html></html>',
            'exercise_id': self.html_ex.id,
        })
        self.assertTrue(resp.json().get('browser_sandbox'))

    def test_css_api_run_returns_browser_sandbox(self):
        resp = _post(self.client, {
            'language_slug': 'css',
            'code': 'body { color: red; }',
            'exercise_id': self.css_ex.id,
        })
        self.assertTrue(resp.json().get('browser_sandbox'))

    def test_scratch_exercise_page_loads(self):
        resp = self.client.get(_detail_url('scratch', self.sc_ex.id))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['language'].uses_scratch_vm)
