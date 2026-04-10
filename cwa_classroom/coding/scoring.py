"""
coding.scoring
~~~~~~~~~~~~~~
Unified scoring engine for all coding problems.

Public API
----------
evaluate_submission(problem, code, piston_lang)
        Run student code against every test case for any problem.
        Problem type is determined dynamically from DB metadata — no per-problem
        handler file is needed.

score_submission(eval_result)
        Binary scoring model applied identically to every problem:

                100  all visible + hidden tests passed
                 50  all visible tests passed, at least one hidden test failed
                    0  any visible test failed

        Scores are deterministic — identical code always produces identical scores.

Design goals
------------
* **Single function, all problems** — evaluate_submission + score_submission
    handle Bubble Sort, FizzBuzz, Reverse String, Two Sum, etc. without
    any per-problem branching.
* **Metadata-driven** — problem.category currently drives the output-comparison
    strategy (e.g. numeric tolerance for mathematics).  No hard-coded logic per
    problem title or type.
* **Deterministic** — no randomness, no speed bonus, no quality multiplier.
    Correctness and hidden-test coverage are the only scoring inputs.
* **Testable in isolation** — both functions accept plain arguments so unit
    tests can call them without HTTP or a real Piston server.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output comparison
# ---------------------------------------------------------------------------

def compare_outputs(actual: str, expected: str, category: str) -> bool:
    """Return True when *actual* satisfies *expected* for the given *category*.

    Default (all categories)
        Exact string match after stripping trailing whitespace from both sides.

    Mathematics
        Also accepts numeric equality so '3.0' matches '3', and floating-point
        answers within 1e-6 absolute tolerance are considered correct.

    Args:
        actual:    Raw stdout from the student's program (already .strip()ed).
        expected:  Expected output from the test case (already .strip()ed).
        category:  CodingProblem.category slug, e.g. 'mathematics'.
    """
    if actual == expected:
        return True

    if category == 'mathematics':
        try:
            return abs(float(actual) - float(expected)) < 1e-6
        except (ValueError, TypeError):
            pass

    return False


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TestCaseResult:
    """Result for a single test case execution within evaluate_submission."""

    test_case_id: Optional[int]
    is_visible: bool
    passed: bool
    execution_time: float          # server-measured Piston round-trip (seconds)

    # Populated only for visible test cases (hidden cases never expose output)
    actual_output: str = ''
    expected_output: str = ''
    description: str = ''
    input_data: str = ''


@dataclass
class EvaluationResult:
    """Aggregated result of running a submission against all test cases."""

    test_results: List[TestCaseResult] = field(default_factory=list)
    total_execution_seconds: float = 0.0
    all_passed: bool = True
    visible_passed: int = 0
    visible_total: int = 0
    hidden_passed: int = 0
    hidden_total: int = 0

    @property
    def total_passed(self) -> int:
        return self.visible_passed + self.hidden_passed

    @property
    def total_tests(self) -> int:
        return self.visible_total + self.hidden_total

    @property
    def has_test_cases(self) -> bool:
        return self.visible_total + self.hidden_total > 0

    @property
    def visible_all_passed(self) -> bool:
        """True when every visible test case passed."""
        return self.visible_total > 0 and self.visible_passed == self.visible_total


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------

def evaluate_submission(problem, code: str, piston_lang: str) -> EvaluationResult:
    """Run *code* against every test case for *problem* and return an EvaluationResult.

    This is the single, reusable evaluation function for **all** problem types.
    The problem's ``category`` metadata automatically drives both:

    * **Which comparison strategy to use** — e.g. numeric tolerance for
      mathematics vs. exact string match for algorithm problems.
    * **Which K constant to apply in score_submission()** — tight for sorting,
      relaxed for string manipulation.

    No per-problem handler file is required.  To change how a class of problems
    is evaluated, update K_BY_CATEGORY or compare_outputs() in this module.

    Args:
        problem:      A CodingProblem ORM instance (must have .test_cases related manager).
        code:         Student source code.  Forbidden-pattern checking must be
                      performed by the caller *before* calling this function.
        piston_lang:  Piston API language identifier, e.g. 'python', 'javascript'.

    Returns:
        EvaluationResult with per-test details and aggregate counts.
        If the problem has no test cases, returns an empty EvaluationResult
        with all_passed=True and all counters at zero (caller should reject).
    """
    from .execution import run_code

    category = getattr(problem, 'category', '') or ''
    result = EvaluationResult()

    try:
        test_cases = list(problem.test_cases.all().order_by('display_order', 'id'))
    except Exception as exc:
        # Schema fallback: display_order may not exist yet on fresh installs
        logger.warning(
            'evaluate_submission: display_order ordering failed for problem %s (%s); '
            'falling back to id order.',
            getattr(problem, 'id', '?'), exc,
        )
        test_cases = list(problem.test_cases.all().order_by('id'))

    if not test_cases:
        logger.warning('evaluate_submission: problem %s has no test cases.', getattr(problem, 'id', '?'))
        return result

    for tc in test_cases:
        exec_result = run_code(piston_lang, code, tc.input_data)
        raw_actual = exec_result.get('stdout', '').strip()
        raw_expected = tc.expected_output.strip()
        run_time = float(exec_result.get('run_time_seconds', 0.0) or 0.0)

        passed = (
            compare_outputs(raw_actual, raw_expected, category)
            and exec_result.get('exit_code', 1) == 0
        )

        result.total_execution_seconds += run_time

        if not passed:
            result.all_passed = False

        if tc.is_visible:
            result.visible_total += 1
            if passed:
                result.visible_passed += 1
            result.test_results.append(TestCaseResult(
                test_case_id=tc.id,
                is_visible=True,
                passed=passed,
                execution_time=run_time,
                actual_output=raw_actual,
                expected_output=raw_expected,
                description=tc.description,
                input_data=tc.input_data,
            ))
        else:
            result.hidden_total += 1
            if passed:
                result.hidden_passed += 1
            result.test_results.append(TestCaseResult(
                test_case_id=tc.id,
                is_visible=False,
                passed=passed,
                execution_time=run_time,
                # actual_output intentionally omitted — never expose hidden output
            ))

    return result


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_submission(eval_result: EvaluationResult) -> float:
    """Return a deterministic binary score for *eval_result*.

    Scoring tiers
    -------------
    100.0  All visible **and** all hidden tests passed.
     50.0  All visible tests passed; at least one hidden test failed.
      0.0  Any visible test failed (or no test cases configured).

    This rule applies identically to every problem regardless of category,
    difficulty, language, or execution time.  Scores are always one of
    {0.0, 50.0, 100.0} — never a mid-range value.

    Args:
        eval_result: EvaluationResult from evaluate_submission().

    Returns:
        Float: 0.0, 50.0, or 100.0.
    """
    if not eval_result.has_test_cases:
        return 0.0

    if eval_result.all_passed:
        return 100.0

    if eval_result.visible_all_passed:
        # Visible tests all pass but at least one hidden test failed
        return 50.0

    return 0.0
