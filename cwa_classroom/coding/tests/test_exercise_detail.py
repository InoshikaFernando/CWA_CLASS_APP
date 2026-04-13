"""
test_exercise_detail.py
~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive unittest suite for Exercise Detail pages — text-editor and Scratch block-based.

Screenshot references:
  - Text editor: "Hello, World!" exercise — difficulty label, title, instructions,
    "Show hint" button, editor with file name "main.py", run/reset buttons,
    output panel "Click 'Run Code' to see your output here.", "✓ Completed" state.
  - Scratch: "Count Down" exercise — block workspace, categories (Output/Control/
    Variables/Math/Logic/Text/Lists), "scratch.py" file label, "Generated Python" panel,
    expected countdown 10 → 1 output.

Views tested:
  - coding.views.exercise_detail  GET /coding/<lang>/exercise/<id>/

Covers:
  1. Authentication guard
  2. Text-editor exercises: Python, JavaScript, HTML/CSS
  3. Exercise metadata in context: title, level, instructions, hints
  4. Completion state: is_completed flag
  5. server_blocks_xml: empty for text editors, populated for Scratch
  6. Scratch exercise: workspace restore cascade (latest submission → starter)
  7. Multiple Scratch submissions: latest blocks_xml is used
  8. 404 for inactive/wrong-language exercises
  9. All five languages have working exercise pages
  10. Log validation — no silent failures
  11. Error handling: invalid exercise_id
"""
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingTopic,
    StudentExerciseSubmission,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lang(slug, name, order=1, active=True):
    lang, _ = CodingLanguage.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'color': '#000', 'order': order,
                  'is_active': active, 'description': f'{name} programming language'},
    )
    return lang


def _topic(lang, name, slug, order=1):
    return CodingTopic.objects.create(
        language=lang, name=name, slug=slug, order=order, is_active=True,
    )


def _exercise(
    topic, title,
    level=CodingExercise.BEGINNER,
    starter='# Write your code here\n',
    expected='',
    hints='',
    order=1,
    active=True,
):
    return CodingExercise.objects.create(
        topic=topic, level=level, title=title,
        description=f'Instructions for {title}.',
        starter_code=starter,
        expected_output=expected,
        hints=hints,
        order=order,
        is_active=active,
    )


def _complete(student, exercise, code='print("done")', output='done', blocks_xml=''):
    return StudentExerciseSubmission.objects.create(
        student=student, exercise=exercise,
        code_submitted=code, output_received=output,
        is_completed=True, blocks_xml=blocks_xml,
    )


def _incomplete(student, exercise, code='# wip', blocks_xml=''):
    return StudentExerciseSubmission.objects.create(
        student=student, exercise=exercise,
        code_submitted=code, is_completed=False, blocks_xml=blocks_xml,
    )


def _detail_url(lang_slug, exercise_id):
    return reverse('coding:exercise_detail', args=[lang_slug, exercise_id])


# ===========================================================================
# 1. Authentication guard
# ===========================================================================

class TestExerciseDetailAuth(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang = _lang('python', 'Python')
        t = _topic(lang, 'Variables', 'py-vars-auth')
        cls.exercise = _exercise(t, 'Hello World')

    def test_unauthenticated_redirects(self):
        resp = self.client.get(_detail_url('python', self.exercise.id))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'].lower())


# ===========================================================================
# 2. Python text-editor exercise — positive path
# ===========================================================================

class TestPythonExerciseDetail(TestCase):
    """
    Screenshot reference: "Hello, World!" beginner exercise in Python.
    Verify metadata, context variables, completion state, file label.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('py_ex_student', password='pass', email='py_ex_student@test.com')
        cls.lang = _lang('python', 'Python')
        t = _topic(cls.lang, 'Variables', 'py-vars-py')
        cls.exercise = _exercise(
            t, 'Hello, World!',
            level=CodingExercise.BEGINNER,
            starter='# Write your code here\nprint("Hello, World!")',
            expected='Hello, World!',
            hints='Use the print() function.',
        )

    def setUp(self):
        self.client.force_login(self.student)
        self.resp = self.client.get(_detail_url('python', self.exercise.id))

    def test_returns_200(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_correct_template(self):
        self.assertTemplateUsed(self.resp, 'coding/exercise_detail.html')

    def test_language_in_context(self):
        self.assertEqual(self.resp.context['language'].slug, 'python')

    def test_exercise_in_context(self):
        self.assertEqual(self.resp.context['exercise'].title, 'Hello, World!')

    def test_exercise_level_is_beginner(self):
        """Difficulty label must be 'Beginner'."""
        ex = self.resp.context['exercise']
        self.assertEqual(ex.level, CodingExercise.BEGINNER)
        self.assertEqual(ex.get_level_display(), 'Beginner')

    def test_exercise_description_present(self):
        """Instructions text must be non-empty."""
        self.assertTrue(self.resp.context['exercise'].description)

    def test_exercise_hints_present(self):
        """'Show hint' button is available only when hints are non-empty."""
        self.assertTrue(self.resp.context['exercise'].hints)

    def test_starter_code_present(self):
        """Editor must be pre-filled with starter code."""
        self.assertTrue(self.resp.context['exercise'].starter_code)

    def test_is_completed_false_initially(self):
        """Fresh student has not completed the exercise yet."""
        self.assertFalse(self.resp.context['is_completed'])

    def test_server_blocks_xml_empty_for_python(self):
        """Python is not a Scratch exercise — server_blocks_xml must be empty."""
        self.assertEqual(self.resp.context['server_blocks_xml'], '')

    def test_subject_sidebar_is_coding(self):
        self.assertEqual(self.resp.context['subject_sidebar'], 'coding')

    def test_is_completed_true_after_submission(self):
        """After a completed submission the is_completed flag must be True."""
        _complete(self.student, self.exercise)
        resp = self.client.get(_detail_url('python', self.exercise.id))
        self.assertTrue(resp.context['is_completed'])

    def test_incomplete_submission_does_not_set_is_completed(self):
        """An incomplete (in-progress) submission must NOT set is_completed."""
        _incomplete(self.student, self.exercise)
        resp = self.client.get(_detail_url('python', self.exercise.id))
        self.assertFalse(resp.context['is_completed'])

    def test_language_not_scratch_vm(self):
        """Python language must not be flagged as a Scratch VM language."""
        self.assertFalse(self.resp.context['language'].uses_scratch_vm)

    def test_language_not_browser_sandbox(self):
        """Python must not be flagged as a browser sandbox language."""
        self.assertFalse(self.resp.context['language'].uses_browser_sandbox)


# ===========================================================================
# 3. JavaScript text-editor exercise
# ===========================================================================

class TestJavaScriptExerciseDetail(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('js_ex_student', password='pass', email='js_ex_student@test.com')
        cls.lang = _lang('javascript', 'JavaScript', order=2)
        t = _topic(cls.lang, 'Functions', 'js-functions-js')
        cls.exercise = _exercise(
            t, 'Console Hello',
            level=CodingExercise.BEGINNER,
            starter='// Write your code here\nconsole.log("Hello, World!");',
            hints='Use console.log()',
        )

    def setUp(self):
        self.client.force_login(self.student)
        self.resp = self.client.get(_detail_url('javascript', self.exercise.id))

    def test_returns_200(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_language_is_javascript(self):
        self.assertEqual(self.resp.context['language'].slug, 'javascript')

    def test_server_blocks_xml_empty(self):
        self.assertEqual(self.resp.context['server_blocks_xml'], '')

    def test_not_scratch_vm(self):
        self.assertFalse(self.resp.context['language'].uses_scratch_vm)

    def test_not_browser_sandbox(self):
        self.assertFalse(self.resp.context['language'].uses_browser_sandbox)

    def test_completion_cycle(self):
        """Start incomplete → complete → is_completed=True."""
        self.assertFalse(self.resp.context['is_completed'])
        _complete(self.student, self.exercise)
        resp2 = self.client.get(_detail_url('javascript', self.exercise.id))
        self.assertTrue(resp2.context['is_completed'])


# ===========================================================================
# 4. HTML/CSS browser-sandbox exercise
# ===========================================================================

class TestHtmlExerciseDetail(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('html_ex_student', password='pass', email='html_ex_student@test.com')
        cls.lang = _lang('html', 'HTML', order=3)
        t = _topic(cls.lang, 'Structure', 'html-structure-html')
        cls.exercise = _exercise(
            t, 'My First Page',
            level=CodingExercise.BEGINNER,
            starter='<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>',
        )

    def setUp(self):
        self.client.force_login(self.student)
        self.resp = self.client.get(_detail_url('html', self.exercise.id))

    def test_returns_200(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_language_uses_browser_sandbox(self):
        """HTML language must be flagged as browser sandbox → no Piston call."""
        self.assertTrue(self.resp.context['language'].uses_browser_sandbox)

    def test_server_blocks_xml_empty(self):
        self.assertEqual(self.resp.context['server_blocks_xml'], '')

    def test_is_completed_false_initially(self):
        self.assertFalse(self.resp.context['is_completed'])


# ===========================================================================
# 5. Scratch block-based exercise — positive path
# ===========================================================================

class TestScratchExerciseDetail(TestCase):
    """
    Screenshot reference: "Count Down" Scratch exercise.
    Blockly workspace XML is stored in blocks_xml and restored on next visit.
    Expected: server_blocks_xml populated from the student's last submission.
    """

    STARTER_XML = '<xml xmlns="https://developers.google.com/blockly/xml"></xml>'
    SAVED_XML = (
        '<xml xmlns="https://developers.google.com/blockly/xml">'
        '<block type="controls_repeat_ext" x="10" y="10"></block>'
        '</xml>'
    )
    UPDATED_XML = (
        '<xml xmlns="https://developers.google.com/blockly/xml">'
        '<block type="text_print" x="10" y="10"></block>'
        '</xml>'
    )

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('sc_ex_student', password='pass', email='sc_ex_student@test.com')
        cls.lang = _lang('scratch', 'Scratch', order=5)
        t = _topic(cls.lang, 'Control', 'scratch-control-sc')
        cls.exercise = _exercise(
            t, 'Count Down',
            level=CodingExercise.BEGINNER,
            starter=cls.STARTER_XML,
            hints='Use a repeat block and a say block.',
        )

    def setUp(self):
        self.client.force_login(self.student)

    def test_returns_200(self):
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.status_code, 200)

    def test_language_uses_scratch_vm(self):
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertTrue(resp.context['language'].uses_scratch_vm)

    def test_server_blocks_xml_empty_when_no_submission(self):
        """Without any previous submission, server_blocks_xml must be empty string."""
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['server_blocks_xml'], '')

    def test_server_blocks_xml_restored_from_completed_submission(self):
        """After a completed submission, server_blocks_xml must equal the saved XML."""
        _complete(self.student, self.exercise,
                  code='print(10)\nprint(9)\nprint(8)',
                  blocks_xml=self.SAVED_XML)
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['server_blocks_xml'], self.SAVED_XML)

    def test_server_blocks_xml_restored_from_incomplete_submission(self):
        """Even an in-progress Scratch submission must restore the workspace."""
        _incomplete(self.student, self.exercise, blocks_xml=self.SAVED_XML)
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['server_blocks_xml'], self.SAVED_XML)

    def test_server_blocks_xml_uses_latest_submission(self):
        """When multiple submissions exist, the most recent blocks_xml is used."""
        # First (older) submission
        _complete(self.student, self.exercise, blocks_xml=self.SAVED_XML)
        # Second (newer) submission — different XML
        StudentExerciseSubmission.objects.create(
            student=self.student,
            exercise=self.exercise,
            code_submitted='print(10)',
            is_completed=True,
            blocks_xml=self.UPDATED_XML,
        )
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        # Must use the most recently submitted blocks_xml
        self.assertEqual(resp.context['server_blocks_xml'], self.UPDATED_XML)

    def test_server_blocks_xml_empty_when_submission_has_no_xml(self):
        """A submission with blocks_xml='' must still produce server_blocks_xml=''."""
        StudentExerciseSubmission.objects.create(
            student=self.student, exercise=self.exercise,
            code_submitted='print("hi")', is_completed=True, blocks_xml='',
        )
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['server_blocks_xml'], '')

    def test_is_completed_false_initially(self):
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertFalse(resp.context['is_completed'])

    def test_is_completed_true_after_completion(self):
        _complete(self.student, self.exercise, blocks_xml=self.SAVED_XML)
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertTrue(resp.context['is_completed'])

    def test_exercise_has_hint_text(self):
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertTrue(resp.context['exercise'].hints)

    def test_exercise_level_is_beginner(self):
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['exercise'].get_level_display(), 'Beginner')


# ===========================================================================
# 6. Scratch student isolation
# ===========================================================================

class TestScratchExerciseStudentIsolation(TestCase):
    """Student A's blocks_xml must not appear in Student B's workspace."""

    STARTER_XML = '<xml xmlns="https://developers.google.com/blockly/xml"></xml>'
    A_XML = '<xml><block type="controls_repeat_ext"></block></xml>'

    @classmethod
    def setUpTestData(cls):
        cls.studentA = User.objects.create_user('sc_iso_A', password='pass', email='sc_iso_a@test.com')
        cls.studentB = User.objects.create_user('sc_iso_B', password='pass', email='sc_iso_b@test.com')
        lang = _lang('scratch', 'Scratch', order=5)
        t = _topic(lang, 'Variables', 'scratch-vars-iso')
        cls.exercise = _exercise(t, 'Store and Print', starter=cls.STARTER_XML)
        _complete(cls.studentA, cls.exercise, blocks_xml=cls.A_XML)

    def test_student_b_sees_empty_xml(self):
        """Student B has no submission → server_blocks_xml must be empty."""
        self.client.force_login(self.studentB)
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['server_blocks_xml'], '')

    def test_student_a_sees_own_xml(self):
        self.client.force_login(self.studentA)
        resp = self.client.get(_detail_url('scratch', self.exercise.id))
        self.assertEqual(resp.context['server_blocks_xml'], self.A_XML)


# ===========================================================================
# 7. 404 error handling
# ===========================================================================

class TestExerciseDetailErrors(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('err_student', password='pass', email='err_student@test.com')
        cls.py_lang = _lang('python', 'Python')
        cls.js_lang = _lang('javascript', 'JavaScript', order=2)
        py_topic = _topic(cls.py_lang, 'Basics', 'py-basics-err')
        cls.py_exercise = _exercise(py_topic, 'Python Exercise')
        js_topic = _topic(cls.js_lang, 'Basics', 'js-basics-err')
        cls.js_exercise = _exercise(js_topic, 'JS Exercise')

    def setUp(self):
        self.client.force_login(self.student)

    def test_404_for_nonexistent_exercise_id(self):
        resp = self.client.get(_detail_url('python', 99999))
        self.assertEqual(resp.status_code, 404)

    def test_404_for_inactive_exercise(self):
        """An inactive exercise must return 404."""
        py_topic = _topic(self.py_lang, 'Extra', 'py-extra-err')
        inactive_ex = _exercise(py_topic, 'Inactive', active=False)
        resp = self.client.get(_detail_url('python', inactive_ex.id))
        self.assertEqual(resp.status_code, 404)

    def test_404_when_exercise_belongs_to_wrong_language(self):
        """A Python exercise accessed under the JavaScript URL must return 404."""
        resp = self.client.get(_detail_url('javascript', self.py_exercise.id))
        self.assertEqual(resp.status_code, 404)

    def test_404_for_invalid_language_slug(self):
        resp = self.client.get(_detail_url('cobol', self.py_exercise.id))
        self.assertEqual(resp.status_code, 404)

    def test_404_for_inactive_language(self):
        inactive_lang = _lang('ruby', 'Ruby', order=9, active=False)
        t = CodingTopic.objects.create(
            language=inactive_lang, name='Basics', slug='ruby-basics',
            order=1, is_active=True,
        )
        ex = _exercise(t, 'Ruby Ex')
        resp = self.client.get(_detail_url('ruby', ex.id))
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# 8. All five languages have working exercise detail pages
# ===========================================================================

class TestAllLanguagesExerciseDetail(TestCase):
    """Parametric-style test: all five language slugs must produce 200 responses."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('all_lang_student', password='pass', email='all_lang_student@test.com')
        cls.exercises = {}
        for order, (slug, name) in enumerate([
            ('python', 'Python'),
            ('javascript', 'JavaScript'),
            ('html', 'HTML'),
            ('css', 'CSS'),
            ('scratch', 'Scratch'),
        ], start=1):
            lang = _lang(slug, name, order=order)
            t = _topic(lang, f'{name} Basics', f'{slug}-basics-all-langs')
            ex = _exercise(t, f'{name} Intro Exercise')
            cls.exercises[slug] = ex

    def setUp(self):
        self.client.force_login(self.student)

    def test_python_exercise_returns_200(self):
        ex = self.exercises['python']
        self.assertEqual(self.client.get(_detail_url('python', ex.id)).status_code, 200)

    def test_javascript_exercise_returns_200(self):
        ex = self.exercises['javascript']
        self.assertEqual(self.client.get(_detail_url('javascript', ex.id)).status_code, 200)

    def test_html_exercise_returns_200(self):
        ex = self.exercises['html']
        self.assertEqual(self.client.get(_detail_url('html', ex.id)).status_code, 200)

    def test_css_exercise_returns_200(self):
        ex = self.exercises['css']
        self.assertEqual(self.client.get(_detail_url('css', ex.id)).status_code, 200)

    def test_scratch_exercise_returns_200(self):
        ex = self.exercises['scratch']
        self.assertEqual(self.client.get(_detail_url('scratch', ex.id)).status_code, 200)

    def test_html_uses_browser_sandbox(self):
        resp = self.client.get(_detail_url('html', self.exercises['html'].id))
        self.assertTrue(resp.context['language'].uses_browser_sandbox)

    def test_css_uses_browser_sandbox(self):
        resp = self.client.get(_detail_url('css', self.exercises['css'].id))
        self.assertTrue(resp.context['language'].uses_browser_sandbox)

    def test_scratch_uses_scratch_vm(self):
        resp = self.client.get(_detail_url('scratch', self.exercises['scratch'].id))
        self.assertTrue(resp.context['language'].uses_scratch_vm)

    def test_python_piston_language_is_python(self):
        resp = self.client.get(_detail_url('python', self.exercises['python'].id))
        self.assertEqual(resp.context['language'].piston_language, 'python')

    def test_javascript_piston_language_is_javascript(self):
        resp = self.client.get(_detail_url('javascript', self.exercises['javascript'].id))
        self.assertEqual(resp.context['language'].piston_language, 'javascript')

    def test_html_piston_language_is_none(self):
        resp = self.client.get(_detail_url('html', self.exercises['html'].id))
        self.assertIsNone(resp.context['language'].piston_language)

    def test_scratch_piston_language_is_none(self):
        resp = self.client.get(_detail_url('scratch', self.exercises['scratch'].id))
        self.assertIsNone(resp.context['language'].piston_language)


# ===========================================================================
# 9. Exercise level progression: Beginner → Intermediate → Advanced
# ===========================================================================

class TestExerciseLevelProgression(TestCase):
    """
    All three difficulty levels must be accessible via exercise_detail.
    Each level carries the correct display label.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('level_prog_student', password='pass', email='level_prog_student@test.com')
        lang = _lang('python', 'Python')
        t = _topic(lang, 'Functions', 'py-funcs-levels')
        cls.beg_ex = _exercise(t, 'Beginner Ex',     level=CodingExercise.BEGINNER)
        cls.int_ex = _exercise(t, 'Intermediate Ex', level=CodingExercise.INTERMEDIATE)
        cls.adv_ex = _exercise(t, 'Advanced Ex',     level=CodingExercise.ADVANCED)

    def setUp(self):
        self.client.force_login(self.student)

    def test_beginner_level_display(self):
        resp = self.client.get(_detail_url('python', self.beg_ex.id))
        self.assertEqual(resp.context['exercise'].get_level_display(), 'Beginner')

    def test_intermediate_level_display(self):
        resp = self.client.get(_detail_url('python', self.int_ex.id))
        self.assertEqual(resp.context['exercise'].get_level_display(), 'Intermediate')

    def test_advanced_level_display(self):
        resp = self.client.get(_detail_url('python', self.adv_ex.id))
        self.assertEqual(resp.context['exercise'].get_level_display(), 'Advanced')

    def test_beginner_completion_does_not_mark_intermediate_complete(self):
        """Completing the beginner exercise must not affect the intermediate flag."""
        _complete(self.student, self.beg_ex)
        resp = self.client.get(_detail_url('python', self.int_ex.id))
        self.assertFalse(resp.context['is_completed'])


# ===========================================================================
# 10. Log validation — no silent failures on exercise_detail
# ===========================================================================

class TestExerciseDetailLogging(TestCase):
    """
    exercise_detail must not emit WARNING/ERROR logs during happy-path
    operation, for both text-editor and Scratch exercises.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('log_ex_student', password='pass', email='log_ex_student@test.com')
        py_lang = _lang('python', 'Python')
        sc_lang = _lang('scratch', 'Scratch', order=5)

        py_t = _topic(py_lang, 'Logging Topic', 'py-log-topic')
        sc_t = _topic(sc_lang, 'Scratch Log Topic', 'sc-log-topic')

        cls.py_ex = _exercise(py_t, 'Py Log Exercise')
        cls.sc_ex = _exercise(
            sc_t, 'Scratch Log Exercise',
            starter='<xml xmlns="https://developers.google.com/blockly/xml"></xml>',
        )

    def setUp(self):
        self.client.force_login(self.student)

    def test_no_warning_on_python_exercise_load(self):
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.WARNING):
                resp = self.client.get(_detail_url('python', self.py_ex.id))
            self.assertEqual(resp.status_code, 200)
        else:
            resp = self.client.get(_detail_url('python', self.py_ex.id))
            self.assertEqual(resp.status_code, 200)

    def test_no_warning_on_scratch_exercise_load(self):
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.WARNING):
                resp = self.client.get(_detail_url('scratch', self.sc_ex.id))
            self.assertEqual(resp.status_code, 200)
        else:
            resp = self.client.get(_detail_url('scratch', self.sc_ex.id))
            self.assertEqual(resp.status_code, 200)

    def test_no_warning_when_scratch_has_prior_submission(self):
        """Restoring blocks_xml from a prior submission must produce no warnings."""
        _complete(self.student, self.sc_ex, blocks_xml='<xml><block></block></xml>')
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.WARNING):
                resp = self.client.get(_detail_url('scratch', self.sc_ex.id))
            self.assertEqual(resp.status_code, 200)


# ===========================================================================
# 11. api_submit_problem logging — Warning for no test cases
# ===========================================================================

class TestApiSubmitProblemWarningLogs(TestCase):
    """
    api_submit_problem emits a WARNING log when a problem has zero test cases.
    Verify this with assertLogs to ensure the log is emitted and not swallowed.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('warn_log_student', password='pass', email='warn_log_student@test.com')
        from coding.models import CodingProblem
        lang = _lang('python', 'Python')
        cls.problem = CodingProblem.objects.create(
            language=lang,
            title='No Tests Problem',
            description='A problem with no test cases.',
            starter_code='', difficulty=1, is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.student)

    def test_warning_emitted_for_zero_test_cases(self):
        """
        When a problem has no test cases, the view must emit a WARNING log
        (not silently return 200 or raise an uncaught exception).
        """
        import json
        url = reverse('coding:api_submit_problem', args=[self.problem.id])
        with self.assertLogs('coding.views', level=logging.WARNING) as log_ctx:
            resp = self.client.post(
                url,
                data=json.dumps({'code': 'print("hi")'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 400)
        # At least one warning about missing test cases
        self.assertTrue(
            any('no test cases' in msg.lower() or 'test case' in msg.lower()
                for msg in log_ctx.output),
            f'Expected test-case warning in logs. Got: {log_ctx.output}',
        )

    def test_error_response_structure_on_zero_test_cases(self):
        """The 400 response must include error, passed_all=False, attempt_points=0."""
        import json
        url = reverse('coding:api_submit_problem', args=[self.problem.id])
        with self.assertLogs('coding.views', level=logging.WARNING):
            resp = self.client.post(
                url,
                data=json.dumps({'code': 'print("hi")'}),
                content_type='application/json',
            )
        data = resp.json()
        self.assertIn('error', data)
        self.assertFalse(data['passed_all'])
        self.assertEqual(data['attempt_points'], 0.0)
