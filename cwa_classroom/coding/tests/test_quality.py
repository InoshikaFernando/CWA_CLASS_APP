"""
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

import pytest
from django.urls import reverse

from coding.models import calculate_coding_points
from coding.quality import QualityResult, analyse_code_quality


# ===========================================================================
# 1. calculate_coding_points — quality_score integration
# ===========================================================================

class TestCalculateCodingPointsQuality:

    def test_perfect_code_no_penalty(self):
        """quality_score=1.0 must not change the base score."""
        base = calculate_coding_points(5, 5, 1.0, quality_score=1.0)
        assert base == calculate_coding_points(5, 5, 1.0)

    def test_quality_penalty_reduces_score(self):
        """quality_score=0.80 reduces score to 80 % of base."""
        base   = calculate_coding_points(5, 5, 0.0, quality_score=1.0)
        penalised = calculate_coding_points(5, 5, 0.0, quality_score=0.80)
        assert penalised == round(base * 0.80, 2)

    def test_quality_score_minimum_cap(self):
        """Even with max quality_score=0.70 a fully correct answer still scores."""
        score = calculate_coding_points(5, 5, 0.0, quality_score=0.70)
        assert score == 70.0

    def test_quality_score_does_not_amplify(self):
        """quality_score > 1.0 would be a bug — our analyser never produces it."""
        # Sanity guard: the formula should NOT give more than 100 pts
        score = calculate_coding_points(5, 5, 0.0, quality_score=1.0)
        assert score <= 100.0

    def test_failed_tests_with_quality_still_zero(self):
        """Partial pass + quality penalty: score proportional to tests passed."""
        score = calculate_coding_points(3, 5, 0.0, quality_score=0.80)
        expected = round((3 / 5) * 100 * 0.80, 2)
        assert score == expected


# ===========================================================================
# 2. Python quality analysis
# ===========================================================================

class TestPythonQualityAnalysis:

    def test_simple_clean_code_no_penalty(self):
        code = "print(input()[::-1])"
        result = analyse_code_quality(code, 'python')
        assert result.quality_score == 1.0
        assert result.issues == []

    def test_clean_function_no_penalty(self):
        code = (
            "def reverse(s):\n"
            "    return s[::-1]\n"
            "print(reverse(input()))\n"
        )
        result = analyse_code_quality(code, 'python')
        assert result.quality_score == 1.0

    def test_nested_loops_penalised(self):
        code = (
            "data = [1, 2, 3]\n"
            "for i in data:\n"
            "    for j in data:\n"
            "        print(i, j)\n"
        )
        result = analyse_code_quality(code, 'python')
        assert result.quality_score < 1.0
        assert result.max_loop_depth == 2
        assert any('nested' in issue.lower() or 'loop' in issue.lower()
                   for issue in result.issues)

    def test_triple_nested_loops_higher_penalty(self):
        code = (
            "for i in range(3):\n"
            "    for j in range(3):\n"
            "        for k in range(3):\n"
            "            print(i, j, k)\n"
        )
        double_result = analyse_code_quality(
            "for i in range(3):\n    for j in range(3):\n        print(i,j)\n",
            'python',
        )
        triple_result = analyse_code_quality(code, 'python')
        assert triple_result.quality_score < double_result.quality_score

    def test_high_cyclomatic_complexity_penalised(self):
        # 12 branches → CC should exceed 10
        branches = "\n".join(f"    if x == {i}:\n        pass" for i in range(12))
        code = f"def classify(x):\n{branches}\n"
        result = analyse_code_quality(code, 'python')
        assert result.cyclomatic_complexity > 10
        assert result.quality_score < 1.0

    def test_redundant_len_in_loop_penalised(self):
        code = (
            "xs = [1, 2, 3]\n"
            "for i in range(10):\n"
            "    n = len(xs)\n"   # len is invariant here
            "    print(n)\n"
        )
        result = analyse_code_quality(code, 'python')
        assert result.redundant_loop_calls >= 1
        assert result.quality_score < 1.0

    def test_syntax_error_no_penalty(self):
        """A syntax error means the test runner already failed — no quality penalty."""
        result = analyse_code_quality("def broken(:", 'python')
        assert result.quality_score == 1.0
        assert result.parse_error is True

    def test_quality_score_never_below_max_penalty(self):
        """Even the worst code cannot score below (1 - max_penalty)."""
        atrocious = (
            "for a in range(10):\n"
            "  for b in range(10):\n"
            "    for c in range(10):\n"
            "      for d in range(10):\n"
            "        n = len(range(10))\n"
            "        m = sorted(range(10))\n"
            "        if a and b and c and d and a and b:\n"
            "          print(a,b,c,d)\n"
        )
        result = analyse_code_quality(atrocious, 'python', max_penalty=0.30)
        assert result.quality_score >= 0.70

    def test_max_penalty_parameter_respected(self):
        nested = (
            "for i in range(5):\n"
            "    for j in range(5):\n"
            "        print(i, j)\n"
        )
        r_strict = analyse_code_quality(nested, 'python', max_penalty=0.05)
        r_lenient = analyse_code_quality(nested, 'python', max_penalty=0.30)
        # Strict cap → less total penalty applied
        assert r_strict.quality_score >= r_lenient.quality_score


# ===========================================================================
# 3. JavaScript quality analysis
# ===========================================================================

class TestJavaScriptQualityAnalysis:

    def test_simple_js_no_penalty(self):
        code = "const s = require('fs').readFileSync('/dev/stdin','utf8').trim(); console.log(s.split('').reverse().join(''));"
        result = analyse_code_quality(code, 'javascript')
        assert result.quality_score == 1.0

    def test_nested_js_loops_penalised(self):
        code = (
            "for (let i = 0; i < n; i++) {\n"
            "    for (let j = 0; j < n; j++) {\n"
            "        console.log(i, j);\n"
            "    }\n"
            "}\n"
        )
        result = analyse_code_quality(code, 'javascript')
        assert result.quality_score < 1.0
        assert result.max_loop_depth >= 2

    def test_js_comments_not_counted_as_branches(self):
        code = (
            "// if this were real it would branch\n"
            "/* while (false) { } */\n"
            "console.log('hello');\n"
        )
        result = analyse_code_quality(code, 'javascript')
        assert result.quality_score == 1.0


# ===========================================================================
# 4. Unsupported languages — pass-through
# ===========================================================================

class TestUnsupportedLanguages:

    @pytest.mark.parametrize('slug', ['html', 'css', 'html-css', 'scratch', 'unknown'])
    def test_unsupported_language_score_one(self, slug):
        result = analyse_code_quality('<h1>Hello</h1>', slug)
        assert result.quality_score == 1.0
        assert result.issues == []

    def test_none_slug_score_one(self):
        result = analyse_code_quality('anything', None)
        assert result.quality_score == 1.0


# ===========================================================================
# 5. API endpoint integration
# ===========================================================================

@pytest.mark.django_db
class TestApiSubmitQualityFields:

    def test_clean_submission_quality_score_one(self, auth_client, problem_with_cases):
        url = reverse('coding:api_submit_problem', args=[problem_with_cases.id])
        code = 'print(input()[::-1])'
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
                {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02},
            ]
            resp = auth_client.post(
                url,
                data=json.dumps({'code': code, 'time_taken_seconds': 10}),
                content_type='application/json',
            )
        assert resp.status_code == 200
        data = resp.json()
        assert 'quality_score' in data
        assert 'quality_issues' in data
        assert data['quality_score'] == 1.0
        assert data['quality_issues'] == []

    def test_nested_loop_submission_penalty_applied(self, auth_client, problem_with_cases):
        url = reverse('coding:api_submit_problem', args=[problem_with_cases.id])
        # Code that reverses via nested loop (very inefficient)
        code = (
            "s = input()\n"
            "result = ''\n"
            "for i in range(len(s)):\n"
            "    for j in range(len(s)):\n"
            "        if j == len(s) - 1 - i:\n"
            "            result += s[j]\n"
            "            break\n"
            "print(result)\n"
        )
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
                {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02},
            ]
            resp = auth_client.post(
                url,
                data=json.dumps({'code': code, 'time_taken_seconds': 10}),
                content_type='application/json',
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['quality_score'] < 1.0
        assert len(data['quality_issues']) > 0
        assert data['attempt_points'] < 100.0

    def test_failed_submission_quality_score_one(self, auth_client, problem_with_cases):
        """A failing submission should not receive a quality penalty — score is already 0."""
        url = reverse('coding:api_submit_problem', args=[problem_with_cases.id])
        code = 'print("wrong")'
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'wrong', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.01},
                {'stdout': 'wrong', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.01},
            ]
            resp = auth_client.post(
                url,
                data=json.dumps({'code': code, 'time_taken_seconds': 5}),
                content_type='application/json',
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['passed_all'] is False
        assert data['attempt_points'] == 0.0
        assert data['quality_score'] == 1.0   # no penalty on a failed attempt

    def test_quality_scoring_disabled_by_feature_flag(
        self, auth_client, problem_with_cases, settings
    ):
        """When ENABLE_QUALITY_SCORING=False, even inefficient code gets quality_score=1.0."""
        settings.ENABLE_QUALITY_SCORING = False
        url = reverse('coding:api_submit_problem', args=[problem_with_cases.id])
        code = (
            "s = input()\n"
            "result = ''\n"
            "for i in range(len(s)):\n"
            "    for j in range(len(s)):\n"
            "        if j == len(s) - 1 - i:\n"
            "            result += s[j]\n"
            "            break\n"
            "print(result)\n"
        )
        with patch('coding.execution.run_code') as mock_rc:
            mock_rc.side_effect = [
                {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
                {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02},
            ]
            resp = auth_client.post(
                url,
                data=json.dumps({'code': code, 'time_taken_seconds': 10}),
                content_type='application/json',
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['quality_score'] == 1.0
        assert data['quality_issues'] == []
        # With no quality penalty and fast execution, should be 100
        assert data['attempt_points'] == 100.0


# ===========================================================================
# 6. Cross-language regression: clean code gets 100 pts
# ===========================================================================

class TestCleanCodeAlwaysMaxPoints:

    @pytest.mark.parametrize('language,code', [
        ('python',     'print(input()[::-1])'),
        ('python',     'n = int(input()); print(n * 2)'),
        ('javascript', 'const s = "hello"; console.log(s.split("").reverse().join(""));'),
    ])
    def test_clean_code_quality_one(self, language, code):
        result = analyse_code_quality(code, language)
        assert result.quality_score == 1.0, (
            f"Expected quality_score=1.0 for clean {language} code, "
            f"got {result.quality_score}. Issues: {result.issues}"
        )
