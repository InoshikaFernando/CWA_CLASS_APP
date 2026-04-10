"""
test_scoring.py
~~~~~~~~~~~~~~~
Tests for the unified coding.scoring module.

Covers:
    - score_submission()   binary 100 / 50 / 0 model
    - compare_outputs()    exact match + mathematics tolerance
    - evaluate_submission() integration via api_submit_problem
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coding.models import (
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    ProblemTestCase,
    calculate_coding_points,  # kept in models; no longer used by scoring engine
)
from coding.scoring import (
    EvaluationResult,
    TestCaseResult,
    compare_outputs,
    evaluate_submission,
    score_submission,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# score_submission() — binary model unit tests
# ---------------------------------------------------------------------------

def _make_result(visible_passed, visible_total, hidden_passed, hidden_total):
    """Build an EvaluationResult from pass/total counts."""
    r = EvaluationResult(
        visible_passed=visible_passed,
        visible_total=visible_total,
        hidden_passed=hidden_passed,
        hidden_total=hidden_total,
    )
    r.all_passed = (visible_passed == visible_total and hidden_passed == hidden_total
                    and (visible_total + hidden_total) > 0)
    return r


class TestBinaryScoreSubmission(TestCase):
    """score_submission() must return exactly 0.0, 50.0, or 100.0."""

    def test_all_pass_returns_100(self):
        r = _make_result(2, 2, 3, 3)
        self.assertEqual(score_submission(r), 100.0)

    def test_visible_and_hidden_pass_no_hidden_cases_returns_100(self):
        """A problem with visible tests only: passing all visible → 100."""
        r = _make_result(2, 2, 0, 0)
        r.all_passed = True
        self.assertEqual(score_submission(r), 100.0)

    def test_visible_pass_hidden_fail_returns_50(self):
        r = _make_result(2, 2, 1, 3)   # hidden: 1/3
        self.assertEqual(score_submission(r), 50.0)

    def test_visible_pass_all_hidden_fail_returns_50(self):
        r = _make_result(2, 2, 0, 3)   # hidden: 0/3
        self.assertEqual(score_submission(r), 50.0)

    def test_visible_fail_returns_0(self):
        r = _make_result(1, 2, 3, 3)   # visible: 1/2
        self.assertEqual(score_submission(r), 0.0)

    def test_all_fail_returns_0(self):
        r = _make_result(0, 2, 0, 3)
        self.assertEqual(score_submission(r), 0.0)

    def test_no_test_cases_returns_0(self):
        r = EvaluationResult()         # empty
        self.assertEqual(score_submission(r), 0.0)

    def test_score_is_always_one_of_three_values(self):
        """score_submission must only ever return 0.0, 50.0, or 100.0."""
        cases = [
            _make_result(0, 2, 0, 2),
            _make_result(2, 2, 0, 2),
            _make_result(2, 2, 2, 2),
            _make_result(1, 3, 3, 3),
            _make_result(3, 3, 1, 5),
        ]
        for r in cases:
            result = score_submission(r)
            self.assertIn(result, {0.0, 50.0, 100.0},
                msg=f'Unexpected score {result} for visible={r.visible_passed}/{r.visible_total} '
                    f'hidden={r.hidden_passed}/{r.hidden_total}')

    def test_identical_inputs_produce_identical_score(self):
        """Scoring is deterministic — same EvaluationResult always gives same score."""
        r1 = _make_result(2, 2, 3, 3)
        r2 = _make_result(2, 2, 3, 3)
        self.assertEqual(score_submission(r1), score_submission(r2))


# ---------------------------------------------------------------------------
# compare_outputs() — output comparison unit tests
# ---------------------------------------------------------------------------

class TestCompareOutputs(TestCase):

    def test_exact_match(self):
        self.assertTrue(compare_outputs('hello', 'hello', 'algorithm'))

    def test_exact_mismatch(self):
        self.assertFalse(compare_outputs('hello', 'world', 'algorithm'))

    def test_maths_integer_equality(self):
        self.assertTrue(compare_outputs('3', '3', 'mathematics'))

    def test_maths_float_vs_int(self):
        self.assertTrue(compare_outputs('3.0', '3', 'mathematics'))

    def test_maths_within_tolerance(self):
        self.assertTrue(compare_outputs('3.0000001', '3', 'mathematics'))

    def test_maths_outside_tolerance(self):
        self.assertFalse(compare_outputs('3.01', '3', 'mathematics'))

    def test_non_maths_rejects_float_vs_int(self):
        """Non-maths categories must use exact string match only."""
        self.assertFalse(compare_outputs('3.0', '3', 'algorithm'))


# ---------------------------------------------------------------------------
# Integration — api_submit_problem binary scoring via HTTP
# ---------------------------------------------------------------------------

class TestBinaryScoringIntegration(TestCase):
    """End-to-end: api_submit_problem must return 100 / 50 / 0 exactly."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='binary_student', password='testpass123',
            email='binary_student@test.com',
        )
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.lang,
            title='Binary Score Test Problem',
            description='Print input reversed.',
            starter_code='',
            difficulty=1,
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=cls.problem, input_data='hello', expected_output='olleh',
            is_visible=True, display_order=1, description='Visible',
        )
        ProblemTestCase.objects.create(
            problem=cls.problem, input_data='abc', expected_output='cba',
            is_visible=False, display_order=2, description='Hidden',
        )

    def setUp(self):
        self.client.force_login(self.student)

    def _submit(self, visible_stdout, hidden_stdout):
        url = reverse('coding:api_submit_problem', args=[self.problem.id])
        with patch('coding.execution.run_code') as mock_run:
            mock_run.side_effect = [
                {'stdout': visible_stdout, 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
                {'stdout': hidden_stdout,  'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
            ]
            resp = self.client.post(
                url,
                data=json.dumps({'code': 'print(input()[::-1])'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_all_pass_scores_100(self):
        data = self._submit('olleh', 'cba')
        self.assertEqual(data['attempt_points'], 100.0)
        self.assertTrue(data['passed_all'])
        self.assertTrue(data['is_new_best'])

    def test_visible_pass_hidden_fail_scores_50(self):
        data = self._submit('olleh', 'WRONG')
        self.assertEqual(data['attempt_points'], 50.0)
        self.assertFalse(data['passed_all'])
        self.assertFalse(data['is_new_best'])

    def test_visible_fail_scores_0(self):
        data = self._submit('WRONG', 'cba')
        self.assertEqual(data['attempt_points'], 0.0)
        self.assertFalse(data['passed_all'])

    def test_all_fail_scores_0(self):
        data = self._submit('WRONG', 'WRONG')
        self.assertEqual(data['attempt_points'], 0.0)

    def test_score_is_deterministic_across_attempts(self):
        """Same code run twice must produce the same score."""
        d1 = self._submit('olleh', 'cba')
        d2 = self._submit('olleh', 'cba')
        self.assertEqual(d1['attempt_points'], d2['attempt_points'])
        self.assertEqual(d1['attempt_points'], 100.0)

    def test_quality_score_always_1_in_response(self):
        """quality_score must be 1.0 — quality no longer affects scoring."""
        data = self._submit('olleh', 'cba')
        self.assertEqual(data['quality_score'], 1.0)
        self.assertEqual(data['quality_issues'], [])

    def test_50_score_never_upgrades_best_from_100(self):
        """A 50-point attempt after a 100-point attempt must not lower best_points."""
        # First attempt: pass everything → 100
        d1 = self._submit('olleh', 'cba')
        self.assertEqual(d1['best_points'], 100.0)
        # Second attempt: hidden fails → 50, but best stays 100
        d2 = self._submit('olleh', 'WRONG')
        self.assertEqual(d2['best_points'], 100.0)
        self.assertEqual(d2['attempt_points'], 50.0)
