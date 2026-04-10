"""
test_quality.py
~~~~~~~~~~~~~~~
Tests for coding.quality — static code-quality analyser.

Covers:
  - Python AST analysis (complexity, nesting, loop depth, redundancy)
  - JavaScript heuristic analysis
  - Unsupported language pass-through
  - calculate_coding_points integration with quality_score
  - API endpoint returns quality_score and quality_issues fields
  - Feature flag: ENABLE_QUALITY_SCORING=False bypasses analysis
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from coding.models import (
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    ProblemTestCase,
    calculate_coding_points,
)
from coding.quality import QualityResult, analyse_code_quality

User = get_user_model()


# ===========================================================================
# 1. calculate_coding_points — quality_score integration
# ===========================================================================

class TestCalculateCodingPointsQuality(TestCase):

    def test_perfect_code_no_penalty(self):
        """quality_score=1.0 must not change the base score."""
        base = calculate_coding_points(5, 5, 1.0, quality_score=1.0)
        self.assertEqual(base, calculate_coding_points(5, 5, 1.0))

    def test_quality_penalty_reduces_score(self):
        """quality_score=0.80 reduces score to 80 % of base."""
        base = calculate_coding_points(5, 5, 0.0, quality_score=1.0)
        penalised = calculate_coding_points(5, 5, 0.0, quality_score=0.80)
        self.assertEqual(penalised, round(base * 0.80, 2))

    def test_quality_score_minimum_cap(self):
        """Even with quality_score=0.70 a fully correct answer still scores."""
        score = calculate_coding_points(5, 5, 0.0, quality_score=0.70)
        self.assertEqual(score, 70.0)

    def test_quality_score_does_not_amplify(self):
        """quality_score > 1.0 would be a bug — our analyser never produces it."""
        score = calculate_coding_points(5, 5, 0.0, quality_score=1.0)
        self.assertLessEqual(score, 100.0)

    def test_failed_tests_with_quality_still_zero(self):
        """Partial pass + quality penalty: score proportional to tests passed."""
        score = calculate_coding_points(3, 5, 0.0, quality_score=0.80)
        expected = round((3 / 5) * 100 * 0.80, 2)
        self.assertEqual(score, expected)


# ===========================================================================
# 2. Python quality analysis
# ===========================================================================

class TestPythonQualityAnalysis(TestCase):

    def test_simple_clean_code_no_penalty(self):
        result = analyse_code_quality('print(input()[::-1])', 'python')
        self.assertEqual(result.quality_score, 1.0)
        self.assertEqual(result.issues, [])

    def test_clean_function_no_penalty(self):
        code = (
            'def reverse(s):\n'
            '    return s[::-1]\n'
            'print(reverse(input()))\n'
        )
        result = analyse_code_quality(code, 'python')
        self.assertEqual(result.quality_score, 1.0)

    def test_nested_loops_penalised(self):
        code = (
            'data = [1, 2, 3]\n'
            'for i in data:\n'
            '    for j in data:\n'
            '        print(i, j)\n'
        )
        result = analyse_code_quality(code, 'python')
        self.assertLess(result.quality_score, 1.0)
        self.assertEqual(result.max_loop_depth, 2)
        self.assertTrue(any(
            'nested' in issue.lower() or 'loop' in issue.lower()
            for issue in result.issues
        ))

    def test_triple_nested_loops_higher_penalty(self):
        double_code = 'for i in range(3):\n    for j in range(3):\n        print(i,j)\n'
        triple_code = (
            'for i in range(3):\n'
            '    for j in range(3):\n'
            '        for k in range(3):\n'
            '            print(i, j, k)\n'
        )
        double_result = analyse_code_quality(double_code, 'python')
        triple_result = analyse_code_quality(triple_code, 'python')
        self.assertLess(triple_result.quality_score, double_result.quality_score)

    def test_high_cyclomatic_complexity_penalised(self):
        branches = '\n'.join(f'    if x == {i}:\n        pass' for i in range(12))
        code = f'def classify(x):\n{branches}\n'
        result = analyse_code_quality(code, 'python')
        self.assertGreater(result.cyclomatic_complexity, 10)
        self.assertLess(result.quality_score, 1.0)

    def test_redundant_len_in_loop_penalised(self):
        code = (
            'xs = [1, 2, 3]\n'
            'for i in range(10):\n'
            '    n = len(xs)\n'
            '    print(n)\n'
        )
        result = analyse_code_quality(code, 'python')
        self.assertGreaterEqual(result.redundant_loop_calls, 1)
        self.assertLess(result.quality_score, 1.0)

    def test_syntax_error_no_penalty(self):
        """A syntax error means the test runner already failed — no quality penalty."""
        result = analyse_code_quality('def broken(:', 'python')
        self.assertEqual(result.quality_score, 1.0)
        self.assertTrue(result.parse_error)

    def test_quality_score_never_below_max_penalty(self):
        """Even the worst code cannot score below (1 - max_penalty)."""
        atrocious = (
            'for a in range(10):\n'
            '  for b in range(10):\n'
            '    for c in range(10):\n'
            '      for d in range(10):\n'
            '        n = len(range(10))\n'
            '        m = sorted(range(10))\n'
            '        if a and b and c and d and a and b:\n'
            '          print(a,b,c,d)\n'
        )
        result = analyse_code_quality(atrocious, 'python', max_penalty=0.30)
        self.assertGreaterEqual(result.quality_score, 0.70)

    def test_max_penalty_parameter_respected(self):
        nested = (
            'for i in range(5):\n'
            '    for j in range(5):\n'
            '        print(i, j)\n'
        )
        r_strict = analyse_code_quality(nested, 'python', max_penalty=0.05)
        r_lenient = analyse_code_quality(nested, 'python', max_penalty=0.30)
        # Strict cap → less total penalty applied → higher (or equal) quality score
        self.assertGreaterEqual(r_strict.quality_score, r_lenient.quality_score)


# ===========================================================================
# 3. JavaScript quality analysis
# ===========================================================================

class TestJavaScriptQualityAnalysis(TestCase):

    def test_simple_js_no_penalty(self):
        code = "const s = require('fs').readFileSync('/dev/stdin','utf8').trim(); console.log(s.split('').reverse().join(''));"
        result = analyse_code_quality(code, 'javascript')
        self.assertEqual(result.quality_score, 1.0)

    def test_nested_js_loops_penalised(self):
        code = (
            'for (let i = 0; i < n; i++) {\n'
            '    for (let j = 0; j < n; j++) {\n'
            '        console.log(i, j);\n'
            '    }\n'
            '}\n'
        )
        result = analyse_code_quality(code, 'javascript')
        self.assertLess(result.quality_score, 1.0)
        self.assertGreaterEqual(result.max_loop_depth, 2)

    def test_js_comments_not_counted_as_branches(self):
        code = (
            '// if this were real it would branch\n'
            '/* while (false) { } */\n'
            "console.log('hello');\n"
        )
        result = analyse_code_quality(code, 'javascript')
        self.assertEqual(result.quality_score, 1.0)


# ===========================================================================
# 4. Unsupported languages — pass-through
# ===========================================================================

class TestUnsupportedLanguages(TestCase):

    def _assert_passthrough(self, slug):
        result = analyse_code_quality('<h1>Hello</h1>', slug)
        self.assertEqual(result.quality_score, 1.0)
        self.assertEqual(result.issues, [])

    def test_html(self):
        self._assert_passthrough('html')

    def test_css(self):
        self._assert_passthrough('css')

    def test_html_css(self):
        self._assert_passthrough('html-css')

    def test_scratch(self):
        self._assert_passthrough('scratch')

    def test_unknown(self):
        self._assert_passthrough('unknown')

    def test_none_slug_score_one(self):
        result = analyse_code_quality('anything', None)
        self.assertEqual(result.quality_score, 1.0)


# ===========================================================================
# 5. API endpoint integration
# ===========================================================================

class TestApiSubmitQualityFields(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='quality_student', password='testpass123',
            email='quality_student@test.com',
        )
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.topic, _ = CodingTopic.objects.get_or_create(
            language=cls.lang, slug='qual-variables',
            defaults={'name': 'Variables', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.lang,
            title='Reverse a String',
            description='Read a string and print it reversed.',
            starter_code='s = input()\n',
            difficulty=1,
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=cls.problem,
            input_data='hello', expected_output='olleh',
            is_visible=True, display_order=1, description='Basic word',
        )
        ProblemTestCase.objects.create(
            problem=cls.problem,
            input_data='a', expected_output='a',
            is_visible=False, display_order=2, description='Single char',
        )

    def setUp(self):
        self.client.force_login(self.student)

    def _url(self):
        return reverse('coding:api_submit_problem', args=[self.problem.id])

    def test_clean_submission_quality_score_one(self):
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
                {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02},
            ]
            resp = self.client.post(
                self._url(),
                data=json.dumps({'code': 'print(input()[::-1])', 'time_taken_seconds': 10}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('quality_score', data)
        self.assertIn('quality_issues', data)
        self.assertEqual(data['quality_score'], 1.0)
        self.assertEqual(data['quality_issues'], [])

    def test_nested_loop_submission_penalty_applied(self):
        code = (
            's = input()\n'
            "result = ''\n"
            'for i in range(len(s)):\n'
            '    for j in range(len(s)):\n'
            '        if j == len(s) - 1 - i:\n'
            '            result += s[j]\n'
            '            break\n'
            'print(result)\n'
        )
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
                {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02},
            ]
            resp = self.client.post(
                self._url(),
                data=json.dumps({'code': code, 'time_taken_seconds': 10}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLess(data['quality_score'], 1.0)
        self.assertGreater(len(data['quality_issues']), 0)
        self.assertLess(data['attempt_points'], 100.0)

    def test_failed_submission_quality_score_one(self):
        """A failing submission should not receive a quality penalty — score is already 0."""
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'wrong', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.01},
                {'stdout': 'wrong', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.01},
            ]
            resp = self.client.post(
                self._url(),
                data=json.dumps({'code': 'print("wrong")', 'time_taken_seconds': 5}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['passed_all'])
        self.assertEqual(data['attempt_points'], 0.0)
        self.assertEqual(data['quality_score'], 1.0)   # no penalty on a failed attempt

    @override_settings(ENABLE_QUALITY_SCORING=False)
    def test_quality_scoring_disabled_by_feature_flag(self):
        """When ENABLE_QUALITY_SCORING=False, even inefficient code gets quality_score=1.0."""
        code = (
            's = input()\n'
            "result = ''\n"
            'for i in range(len(s)):\n'
            '    for j in range(len(s)):\n'
            '        if j == len(s) - 1 - i:\n'
            '            result += s[j]\n'
            '            break\n'
            'print(result)\n'
        )
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.0},
                {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.0},
            ]
            resp = self.client.post(
                self._url(),
                data=json.dumps({'code': code, 'time_taken_seconds': 10}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['quality_score'], 1.0)
        self.assertEqual(data['quality_issues'], [])
        self.assertEqual(data['attempt_points'], 100.0)


# ===========================================================================
# 6. Cross-language regression: clean code gets quality_score=1.0
# ===========================================================================

class TestCleanCodeAlwaysMaxPoints(TestCase):

    def _assert_clean(self, language, code):
        result = analyse_code_quality(code, language)
        self.assertEqual(
            result.quality_score, 1.0,
            msg=(
                f'Expected quality_score=1.0 for clean {language} code, '
                f'got {result.quality_score}. Issues: {result.issues}'
            ),
        )

    def test_python_reverse(self):
        self._assert_clean('python', 'print(input()[::-1])')

    def test_python_double(self):
        self._assert_clean('python', 'n = int(input()); print(n * 2)')

    def test_javascript_reverse(self):
        self._assert_clean(
            'javascript',
            'const s = "hello"; console.log(s.split("").reverse().join(""));',
        )
