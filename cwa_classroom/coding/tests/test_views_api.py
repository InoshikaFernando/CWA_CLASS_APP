"""
test_views_api.py
~~~~~~~~~~~~~~~~~
Comprehensive API endpoint tests for the coding app.

Covers:
  - api_run_code        POST /coding/api/run/
  - api_submit_problem  POST /coding/api/submit/<id>/
  - api_update_time_log POST /coding/api/update-time-log/
  - api_piston_health   GET  /coding/api/piston-health/

Known bugs documented inline:
  BUG-004  _save_exercise_submission silently discards submission when
           exercise_id is invalid (no log entry emitted).
"""
import datetime
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import Role

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    TopicLevel,
    CodingTimeLog,
    ProblemTestCase,
    StudentExerciseSubmission,
    StudentProblemSubmission,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Shared Piston mock return values
# ---------------------------------------------------------------------------

_PISTON_PASS   = {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05}
_PISTON_PASS_B = {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02}
_PISTON_FAIL   = {'stdout': 'wrong', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.01}
_PISTON_ERROR  = {'stdout': '', 'stderr': 'Timed out.', 'exit_code': 1,
                  'run_time_seconds': 0.0, 'error': 'timeout'}


def _post(client, url, payload):
    """POST a JSON payload and return the response."""
    return client.post(url, data=json.dumps(payload), content_type='application/json')


# ===========================================================================
# api_run_code  POST /coding/api/run/
# ===========================================================================

class TestApiRunCode(TestCase):
    """Tests for POST /coding/api/run/"""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='run_student', password='testpass123', email='run_student@test.com',
        )
        cls.python_lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.js_lang, _ = CodingLanguage.objects.get_or_create(
            slug='javascript',
            defaults={'name': 'JavaScript', 'color': '#f59e0b', 'order': 2, 'is_active': True},
        )
        cls.html_lang, _ = CodingLanguage.objects.get_or_create(
            slug='html-css',
            defaults={'name': 'HTML / CSS', 'color': '#ef4444', 'order': 3, 'is_active': True},
        )
        cls.scratch_lang, _ = CodingLanguage.objects.get_or_create(
            slug='scratch',
            defaults={'name': 'Scratch', 'color': '#f97316', 'order': 4, 'is_active': True},
        )
        cls.python_topic, _ = CodingTopic.objects.get_or_create(
            language=cls.python_lang, slug='vapi-variables',
            defaults={'name': 'Variables', 'order': 1, 'is_active': True},
        )
        _py_beg_tl, _ = TopicLevel.get_or_create_for(cls.python_topic, CodingExercise.BEGINNER)
        cls.beginner_exercise = CodingExercise.objects.create(
            topic_level=_py_beg_tl,
            title='Hello World',
            description='Print Hello, World!',
            starter_code='# Write your code here\n',
            expected_output='Hello, World!',
            order=1,
            is_active=True,
        )
        cls.scratch_topic = CodingTopic.objects.create(
            language=cls.scratch_lang, name='Motion', slug='motion',
            order=1, is_active=True,
        )
        _sc_beg_tl, _ = TopicLevel.get_or_create_for(cls.scratch_topic, CodingExercise.BEGINNER)
        cls.scratch_exercise = CodingExercise.objects.create(
            topic_level=_sc_beg_tl,
            title='Say Hello',
            description='Print hello using blocks',
            starter_code='<xml></xml>',
            order=1,
            is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.student)

    # ── Auth & HTTP method guards ────────────────────────────────────────────

    def test_unauthenticated_redirects(self):
        unauth = Client()
        resp = _post(unauth, reverse('coding:api_run_code'),
                     {'language_slug': 'python', 'code': 'print(1)'})
        self.assertEqual(resp.status_code, 302)

    def test_get_method_returns_405(self):
        resp = self.client.get(reverse('coding:api_run_code'))
        self.assertEqual(resp.status_code, 405)

    # ── Input validation ─────────────────────────────────────────────────────

    def test_malformed_json_returns_400(self):
        resp = self.client.post(
            reverse('coding:api_run_code'),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_missing_language_slug_returns_400(self):
        resp = _post(self.client, reverse('coding:api_run_code'), {'code': 'print(1)'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_code_returns_400(self):
        resp = _post(self.client, reverse('coding:api_run_code'),
                     {'language_slug': 'python', 'code': ''})
        self.assertEqual(resp.status_code, 400)

    def test_inactive_language_returns_404(self):
        resp = _post(self.client, reverse('coding:api_run_code'),
                     {'language_slug': 'cobol', 'code': 'print(1)'})
        self.assertEqual(resp.status_code, 404)

    # ── Python / JavaScript execution path ──────────────────────────────────

    def test_python_success_returns_stdout(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            resp = _post(self.client, reverse('coding:api_run_code'),
                         {'language_slug': 'python', 'code': 'print(input()[::-1])'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['stdout'], 'olleh')
        self.assertEqual(data['exit_code'], 0)
        self.assertNotIn('error', data)
        mock_rc.assert_called_once_with('python', 'print(input()[::-1])', '')

    def test_javascript_success(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS):
            resp = _post(self.client, reverse('coding:api_run_code'),
                         {'language_slug': 'javascript', 'code': 'console.log("hi")'})
        self.assertEqual(resp.status_code, 200)

    def test_piston_error_is_forwarded_not_raised(self):
        """Piston errors must be forwarded as 200 with error payload, never as 500."""
        with patch('coding.execution.run_code', return_value=_PISTON_ERROR):
            resp = _post(self.client, reverse('coding:api_run_code'),
                         {'language_slug': 'python', 'code': 'while True: pass'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['exit_code'], 1)

    def test_stdin_forwarded_to_piston(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'python',
                'code': 'print(input())',
                'stdin': 'world',
            })
        mock_rc.assert_called_once_with('python', 'print(input())', 'world')

    # ── HTML / CSS browser-sandbox path ─────────────────────────────────────

    def test_html_css_returns_browser_sandbox_flag(self):
        resp = _post(self.client, reverse('coding:api_run_code'),
                     {'language_slug': 'html-css', 'code': '<h1>Hi</h1>'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('browser_sandbox'))

    def test_html_css_never_calls_piston(self):
        with patch('coding.execution.run_code') as mock_rc:
            _post(self.client, reverse('coding:api_run_code'),
                  {'language_slug': 'html-css', 'code': '<h1>Hi</h1>'})
        mock_rc.assert_not_called()

    # ── Scratch execution path ───────────────────────────────────────────────

    def test_scratch_executes_blockly_python_via_piston(self):
        """Blockly-generated Python from a Scratch exercise must run as 'python' via Piston."""
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            resp = _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'scratch',
                'code': 'print("olleh")',
                'blocks_xml': '<xml></xml>',
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['stdout'], 'olleh')
        call_args = mock_rc.call_args[0]
        self.assertEqual(call_args[0], 'python')    # Must be dispatched as Python, not 'scratch'

    def test_scratch_blocks_xml_not_sent_to_piston(self):
        """blocks_xml is workspace state — must not appear in the Piston payload."""
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'scratch',
                'code': 'print("hi")',
                'blocks_xml': '<xml><block type="text_print"></block></xml>',
            })
        self.assertEqual(mock_rc.call_count, 1)
        # run_code receives (language, code, stdin) — blocks_xml is NOT a parameter
        _, positional_args, _ = mock_rc.mock_calls[0]
        self.assertEqual(len(positional_args), 3)

    # ── mark_complete: submission persistence ────────────────────────────────

    def test_mark_complete_creates_exercise_submission(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS):
            resp = _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'python',
                'code': 'print("Hello, World!")',
                'mark_complete': True,
                'exercise_id': self.beginner_exercise.id,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(StudentExerciseSubmission.objects.filter(
            student=self.student,
            exercise=self.beginner_exercise,
            is_completed=True,
        ).exists())

    def test_mark_complete_upgrades_incomplete_to_complete(self):
        """If an incomplete record already exists it must be upgraded, not duplicated."""
        StudentExerciseSubmission.objects.create(
            student=self.student,
            exercise=self.beginner_exercise,
            code_submitted='# draft',
            is_completed=False,
        )
        with patch('coding.execution.run_code', return_value=_PISTON_PASS):
            _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'python',
                'code': 'print("Hello, World!")',
                'mark_complete': True,
                'exercise_id': self.beginner_exercise.id,
            })
        submissions = StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=self.beginner_exercise,
        )
        self.assertEqual(submissions.count(), 1)        # no duplicate
        self.assertTrue(submissions.first().is_completed)

    def test_mark_complete_invalid_exercise_id_no_crash(self):
        """BUG-004: unknown exercise_id causes silent discard with no log entry.
        The API must not crash or return an error — just silently skip.
        """
        with patch('coding.execution.run_code', return_value=_PISTON_PASS):
            resp = _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'python',
                'code': 'print(1)',
                'mark_complete': True,
                'exercise_id': 99999,
            })
        self.assertEqual(resp.status_code, 200)         # must not crash
        self.assertEqual(StudentExerciseSubmission.objects.count(), 0)

    def test_mark_complete_scratch_stores_blocks_xml(self):
        """Scratch mark_complete must persist blocks_xml on the submission record."""
        blocks = '<xml><block type="text_print"></block></xml>'
        with patch('coding.execution.run_code', return_value=_PISTON_PASS):
            _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'scratch',
                'code': 'print("hello")',
                'blocks_xml': blocks,
                'mark_complete': True,
                'exercise_id': self.scratch_exercise.id,
            })
        sub = StudentExerciseSubmission.objects.get(
            student=self.student, exercise=self.scratch_exercise,
        )
        self.assertEqual(sub.blocks_xml, blocks)
        self.assertTrue(sub.is_completed)

    def test_mark_complete_html_saves_without_piston_call(self):
        """HTML mark_complete must save a submission record without touching Piston."""
        html_topic = CodingTopic.objects.create(
            language=self.html_lang, name='Structure', slug='structure',
            order=1, is_active=True,
        )
        _html_beg_tl, _ = TopicLevel.get_or_create_for(html_topic, CodingExercise.BEGINNER)
        exercise = CodingExercise.objects.create(
            topic_level=_html_beg_tl,
            title='My Page', description='A page',
            starter_code='<html></html>', order=1, is_active=True,
        )
        with patch('coding.execution.run_code') as mock_rc:
            resp = _post(self.client, reverse('coding:api_run_code'), {
                'language_slug': 'html-css',
                'code': '<html></html>',
                'mark_complete': True,
                'exercise_id': exercise.id,
            })
        mock_rc.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(StudentExerciseSubmission.objects.filter(
            student=self.student, exercise=exercise, is_completed=True,
        ).exists())


# ===========================================================================
# api_submit_problem  POST /coding/api/submit/<id>/
# ===========================================================================

class TestApiSubmitProblem(TestCase):
    """Tests for POST /coding/api/submit/<id>/"""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='sub_student', password='testpass123', email='sub_student@test.com',
        )
        cls.student2 = User.objects.create_user(
            username='sub_student2', password='testpass123', email='sub_student2@test.com',
        )
        cls.python_lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.scratch_lang, _ = CodingLanguage.objects.get_or_create(
            slug='scratch',
            defaults={'name': 'Scratch', 'color': '#f97316', 'order': 4, 'is_active': True},
        )
        cls.python_problem = CodingProblem.objects.create(
            language=cls.python_lang,
            title='Reverse a String',
            description='Read a string and print it reversed.',
            starter_code='s = input()\n',
            difficulty=1,
            is_active=True,
        )
        # problem_with_cases: 1 visible + 1 hidden test case
        cls.visible_tc = ProblemTestCase.objects.create(
            problem=cls.python_problem,
            input_data='hello', expected_output='olleh',
            is_visible=True, display_order=1, description='Basic word',
        )
        cls.hidden_tc = ProblemTestCase.objects.create(
            problem=cls.python_problem,
            input_data='a', expected_output='a',
            is_visible=False, display_order=2, description='Single char',
        )
        # Language-agnostic problem
        cls.agnostic_problem = CodingProblem.objects.create(
            language=None,
            title='Agnostic Problem',
            description='Solve this in any supported language.',
            starter_code='',
            difficulty=1,
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=cls.agnostic_problem,
            input_data='hello', expected_output='olleh',
            is_visible=True, display_order=1, description='Basic',
        )
        cls.bubble_sort_problem = CodingProblem.objects.create(
            language=cls.python_lang,
            title='Bubble Sort',
            description='Sort the numbers using Bubble Sort only.',
            starter_code='numbers = list(map(int, input().split()))\n',
            difficulty=5,
            category=CodingProblem.SORTING_SEARCHING,
            forbidden_code_patterns=['sorted(', '.sort('],
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=cls.bubble_sort_problem,
            input_data='3 2 1', expected_output='1 2 3',
            is_visible=True, display_order=1, description='Small reverse order',
        )

    def setUp(self):
        self.client.force_login(self.student)

    # ── Auth & HTTP method guards ────────────────────────────────────────────

    def test_unauthenticated_redirects(self):
        unauth = Client()
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        resp = _post(unauth, url, {'code': 'print(1)'})
        self.assertEqual(resp.status_code, 302)

    def test_get_method_returns_405(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 405)

    # ── Input validation ─────────────────────────────────────────────────────

    def test_malformed_json_returns_400(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        resp = self.client.post(url, data='not-json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_empty_code_returns_400(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        resp = _post(self.client, url, {'code': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('code', resp.json()['error'].lower())

    def test_no_test_cases_returns_400_with_error(self):
        """A problem with zero test cases must return 400 with a descriptive error."""
        empty_problem = CodingProblem.objects.create(
            language=self.python_lang,
            title='Empty Problem',
            description='No test cases.',
            starter_code='',
            difficulty=1,
            is_active=True,
        )
        url = reverse('coding:api_submit_problem', args=[empty_problem.id])
        with patch('coding.execution.run_code'):
            resp = _post(self.client, url, {'code': 'print(input()[::-1])'})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn('error', data)
        self.assertFalse(data['passed_all'])
        self.assertEqual(data['attempt_points'], 0.0)

    # ── 404 for unknown problem ──────────────────────────────────────────────

    def test_problem_not_found_returns_404(self):
        """get_object_or_404 is now outside the outer try/except block so Http404
        propagates correctly instead of being swallowed as a 500."""
        url = reverse('coding:api_submit_problem', args=[99999])
        resp = _post(self.client, url, {'code': 'print("hi")'})
        self.assertEqual(resp.status_code, 404)

    # ── Language resolution ──────────────────────────────────────────────────

    def test_language_agnostic_problem_without_slug_returns_400(self):
        """Problems with language=None require language_slug in the request body."""
        url = reverse('coding:api_submit_problem', args=[self.agnostic_problem.id])
        resp = _post(self.client, url, {'code': 'print("hi")'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('language_slug', resp.json()['error'].lower())

    def test_language_agnostic_problem_with_slug_succeeds(self):
        """A language_slug in the body must resolve the execution language for agnostic problems."""
        url = reverse('coding:api_submit_problem', args=[self.agnostic_problem.id])
        with patch('coding.execution.run_code', return_value=_PISTON_PASS):
            resp = _post(self.client, url, {
                'code': 'print(input()[::-1])',
                'language_slug': 'python',
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['passed_all'])

    def test_scratch_language_rejected_no_piston_support(self):
        """Scratch has piston_language=None; submission via Scratch must return 400."""
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        resp = _post(self.client, url, {
            'code': 'print("hi")',
            'language_slug': 'scratch',
        })
        self.assertEqual(resp.status_code, 400)
        error = resp.json()['error'].lower()
        self.assertTrue('execution' in error or 'support' in error)

    def test_forbidden_shortcut_returns_failed_submission_without_execution(self):
        """Problems can ban shortcuts such as sorted() for Bubble Sort."""
        url = reverse('coding:api_submit_problem', args=[self.bubble_sort_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            resp = _post(self.client, url, {
                'code': 'numbers = list(map(int, input().split()))\nprint(*sorted(numbers))',
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['passed_all'])
        self.assertEqual(data['attempt_points'], 0.0)
        self.assertIn('forbidden shortcut', data['error'].lower())
        self.assertEqual(len(data['visible_results']), 1)
        self.assertFalse(data['visible_results'][0]['passed'])
        mock_rc.assert_not_called()

    def test_forbidden_shortcut_persists_failed_attempt(self):
        """Forbidden shortcut attempts are saved for audit trail and attempt counting."""
        url = reverse('coding:api_submit_problem', args=[self.bubble_sort_problem.id])
        _post(self.client, url, {
            'code': 'numbers = list(map(int, input().split()))\nprint(*sorted(numbers))',
        })
        sub = StudentProblemSubmission.objects.get(
            student=self.student,
            problem=self.bubble_sort_problem,
        )
        self.assertFalse(sub.passed_all_tests)
        self.assertEqual(sub.points, 0.0)
        self.assertEqual(sub.visible_total, 1)
        self.assertEqual(sub.visible_passed, 0)

    # ── All-pass submission ──────────────────────────────────────────────────

    def test_all_pass_correct_response_structure(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
            resp = _post(self.client, url, {'code': 'print(input()[::-1])'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['passed_all'])
        self.assertGreater(data['attempt_points'], 0)
        self.assertEqual(data['best_points'], data['attempt_points'])
        self.assertIn('quality_score', data)
        self.assertIn('quality_issues', data)
        self.assertIn('visible_results', data)
        self.assertIn('hidden_passed', data)
        self.assertIn('hidden_total', data)

    def test_all_pass_first_attempt_is_new_best(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
            resp = _post(self.client, url, {'code': 'print(input()[::-1])'})
        self.assertTrue(resp.json()['is_new_best'])

    def test_all_pass_attempt_points_use_piston_time_not_client_time(self):
        """time_taken_seconds (client-supplied) must be ignored for scoring.
        Binary model: all tests pass → always 100.0 regardless of execution time."""
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        piston_results = [
            {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.10},
            {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
        ]
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = piston_results
            resp = _post(self.client, url, {
                'code': 'print(input()[::-1])',
                'time_taken_seconds': 9999,     # must be ignored for scoring
            })
        self.assertEqual(resp.json()['attempt_points'], 100.0)

    # ── Failure / partial-pass ───────────────────────────────────────────────

    def test_all_fail_returns_zero_attempt_points(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_FAIL, _PISTON_FAIL]
            resp = _post(self.client, url, {'code': 'print("wrong")'})
        data = resp.json()
        self.assertFalse(data['passed_all'])
        self.assertEqual(data['attempt_points'], 0.0)
        self.assertFalse(data['is_new_best'])

    def test_exit_code_nonzero_marks_test_failed(self):
        """A non-zero exit_code must fail the test case even if stdout matches."""
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': 'Error', 'exit_code': 1, 'run_time_seconds': 0.05},
                _PISTON_PASS_B,
            ]
            resp = _post(self.client, url, {'code': 'print(input()[::-1])'})
        data = resp.json()
        self.assertFalse(data['passed_all'])
        self.assertFalse(data['visible_results'][0]['passed'])

    def test_failed_attempt_never_reduces_best_points(self):
        """A failing re-submission must not reduce the student's best (leaderboard) score."""
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])

        # Attempt 1 — pass, earns points
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
            first = _post(self.client, url, {'code': 'print(input()[::-1])'})
        first_best = first.json()['best_points']
        self.assertGreater(first_best, 0)

        # Attempt 2 — fail, best_points must remain unchanged
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_FAIL, _PISTON_FAIL]
            second = _post(self.client, url, {'code': 'print("wrong")'})
        data2 = second.json()
        self.assertEqual(data2['attempt_points'], 0.0)
        self.assertEqual(data2['best_points'], first_best)

    def test_is_new_best_false_on_equal_score(self):
        """Identical execution time on re-submission must produce is_new_best=False."""
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        side_effects = [_PISTON_PASS, _PISTON_PASS_B]

        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = side_effects[:]
            _post(self.client, url, {'code': 'print(input()[::-1])'})   # first

        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = side_effects[:]
            resp2 = _post(self.client, url, {'code': 'print(input()[::-1])'})   # repeat

        # Same Piston time → same points → not strictly greater → not a new best
        self.assertFalse(resp2.json()['is_new_best'])

    # ── Visible vs hidden test case reporting ────────────────────────────────

    def test_visible_results_expose_actual_output(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
            resp = _post(self.client, url, {'code': 'print(input()[::-1])'})
        data = resp.json()
        self.assertEqual(len(data['visible_results']), 1)
        self.assertEqual(data['visible_results'][0]['actual'], 'olleh')
        self.assertTrue(data['visible_results'][0]['passed'])
        self.assertEqual(data['hidden_total'], 1)
        self.assertEqual(data['hidden_passed'], 1)

    # ── DB persistence ───────────────────────────────────────────────────────

    def test_submission_persisted_to_db(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
            _post(self.client, url, {'code': 'print(input()[::-1])'})
        self.assertEqual(
            StudentProblemSubmission.objects.filter(
                student=self.student, problem=self.python_problem,
            ).count(), 1
        )

    def test_attempt_number_increments_on_repeat_submission(self):
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])
        for _ in range(3):
            with patch('coding.execution.run_code') as mock_rc:
                mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
                _post(self.client, url, {'code': 'print(input()[::-1])'})

        attempts = list(
            StudentProblemSubmission.objects
            .filter(student=self.student, problem=self.python_problem)
            .order_by('attempt_number')
            .values_list('attempt_number', flat=True)
        )
        self.assertEqual(attempts, [1, 2, 3])

    def test_student_isolation_separate_attempt_numbers(self):
        """Two different students' attempt counters must be independent."""
        url = reverse('coding:api_submit_problem', args=[self.python_problem.id])

        client2 = Client()
        client2.force_login(self.student2)

        for c in (self.client, client2):
            with patch('coding.execution.run_code') as mock_rc:
                mock_rc.side_effect = [_PISTON_PASS, _PISTON_PASS_B]
                _post(c, url, {'code': 'print(input()[::-1])'})

        for user in (self.student, self.student2):
            num = StudentProblemSubmission.objects.get(
                student=user, problem=self.python_problem,
            ).attempt_number
            self.assertEqual(num, 1)    # each student starts at 1


# ===========================================================================
# api_update_time_log  POST /coding/api/update-time-log/
# ===========================================================================

class TestApiUpdateTimeLog(TestCase):
    """Tests for POST /coding/api/update-time-log/"""

    URL = '/coding/api/update-time-log/'

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='time_student', password='testpass123', email='time_student@test.com',
        )

    def setUp(self):
        self.client.force_login(self.student)

    # ── Auth & HTTP method guards ────────────────────────────────────────────

    def test_unauthenticated_redirects(self):
        unauth = Client()
        resp = _post(unauth, self.URL, {'seconds': 30})
        self.assertEqual(resp.status_code, 302)

    def test_get_method_returns_405(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 405)

    # ── Input validation ─────────────────────────────────────────────────────

    def test_malformed_json_returns_400(self):
        resp = self.client.post(self.URL, data='not-json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_non_numeric_seconds_returns_400(self):
        resp = _post(self.client, self.URL, {'seconds': 'not-a-number'})
        self.assertEqual(resp.status_code, 400)

    # ── No-op guard ─────────────────────────────────────────────────────────

    def test_zero_seconds_returns_ok_without_db_write(self):
        resp = _post(self.client, self.URL, {'seconds': 0})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')
        self.assertFalse(CodingTimeLog.objects.filter(student=self.student).exists())

    def test_negative_seconds_returns_ok_without_db_write(self):
        resp = _post(self.client, self.URL, {'seconds': -5})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CodingTimeLog.objects.filter(student=self.student).exists())

    # ── Happy path ───────────────────────────────────────────────────────────

    def test_valid_seconds_creates_time_log_if_missing(self):
        _post(self.client, self.URL, {'seconds': 30})
        self.assertTrue(CodingTimeLog.objects.filter(student=self.student).exists())

    def test_valid_seconds_accumulates_totals(self):
        _post(self.client, self.URL, {'seconds': 30})
        _post(self.client, self.URL, {'seconds': 20})
        log = CodingTimeLog.objects.get(student=self.student)
        self.assertEqual(log.daily_total_seconds, 50)
        self.assertEqual(log.weekly_total_seconds, 50)

    def test_response_contains_updated_totals(self):
        resp = _post(self.client, self.URL, {'seconds': 45})
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['daily_seconds'], 45)
        self.assertEqual(data['weekly_seconds'], 45)

    def test_daily_reset_occurs_on_new_day(self):
        """Daily total must reset to 0 on the first call of a new calendar day."""
        from django.utils.timezone import localtime
        log = CodingTimeLog.objects.create(
            student=self.student,
            daily_total_seconds=5000,
            weekly_total_seconds=10000,
        )
        yesterday = timezone.now().date() - datetime.timedelta(days=1)
        iso = localtime(timezone.now()).isocalendar()
        current_week = iso[0] * 100 + iso[1]   # year-encoded, e.g. 202615
        CodingTimeLog.objects.filter(pk=log.pk).update(last_reset_date=yesterday, last_reset_week=current_week)

        resp = _post(self.client, self.URL, {'seconds': 30})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['daily_seconds'], 30)
        self.assertEqual(data['weekly_seconds'], 10030)


# ===========================================================================
# student_required guard (elevated roles must be blocked)
# ===========================================================================

class TestStudentRequiredGuard(TestCase):
    """Coding endpoints should redirect elevated non-student roles to home."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(
            username='coding_teacher', password='testpass123', email='coding_teacher@test.com',
        )
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER,
            defaults={'display_name': 'Teacher', 'is_active': True},
        )
        cls.teacher.roles.add(teacher_role)

        cls.python_lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.python_lang,
            title='Guard Test Problem',
            description='Reverse input',
            starter_code='s = input()\n',
            difficulty=1,
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=cls.problem,
            input_data='hello', expected_output='olleh',
            is_visible=True, display_order=1, description='Visible case',
        )

    def setUp(self):
        self.client.force_login(self.teacher)

    def test_api_run_code_teacher_redirected(self):
        resp = _post(self.client, reverse('coding:api_run_code'), {
            'language_slug': 'python',
            'code': 'print(1)',
        })
        self.assertEqual(resp.status_code, 302)

    def test_api_submit_problem_teacher_redirected(self):
        resp = _post(self.client, reverse('coding:api_submit_problem', args=[self.problem.id]), {
            'code': 'print(input()[::-1])',
        })
        self.assertEqual(resp.status_code, 302)

    def test_api_update_time_log_teacher_redirected_and_no_log(self):
        resp = _post(self.client, reverse('coding:api_update_time_log'), {'seconds': 30})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CodingTimeLog.objects.filter(student=self.teacher).exists())


# ===========================================================================
# api_piston_health  GET /coding/api/piston-health/
# ===========================================================================

class TestApiPistonHealth(TestCase):
    """Tests for GET /coding/api/piston-health/"""

    URL = '/coding/api/piston-health/'

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='health_student', password='testpass123',
            email='health_student@test.com',
        )
        cls.staff_user = User.objects.create_user(
            username='health_staff', password='testpass123',
            email='health_staff@test.com',
            is_staff=True, is_superuser=True,
        )

    def setUp(self):
        self.staff_client = Client()
        self.staff_client.force_login(self.staff_user)

    def test_unauthenticated_redirects(self):
        unauth = Client()
        resp = unauth.get(self.URL)
        self.assertEqual(resp.status_code, 302)

    def test_non_staff_returns_403(self):
        self.client.force_login(self.student)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 403)

    def test_staff_piston_ok_returns_200(self):
        with patch('coding.execution.piston_health_check',
                   return_value=(True, 'Piston OK — runtimes: javascript, python')):
            resp = self.staff_client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertIn('Piston OK', data['detail'])

    def test_staff_piston_down_returns_503(self):
        with patch('coding.execution.piston_health_check',
                   return_value=(False, 'Cannot connect to Piston at http://localhost:2000')):
            resp = self.staff_client.get(self.URL)
        self.assertEqual(resp.status_code, 503)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertIn('Cannot connect', data['detail'])

    def test_staff_piston_missing_runtimes_returns_503(self):
        with patch('coding.execution.piston_health_check',
                   return_value=(False, 'Piston up but missing runtimes: javascript')):
            resp = self.staff_client.get(self.URL)
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(resp.json()['ok'])
