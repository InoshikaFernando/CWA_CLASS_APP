"""
test_models_advanced.py
~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for coding.models — class methods, properties, and edge cases.

Covers:
  - calculate_coding_points  edge cases (zero division, rounding, quality integration)
  - CodingLanguage           piston_language, uses_browser_sandbox, uses_scratch_vm
  - CodingProblem            visible_test_cases, hidden_test_cases, total_test_cases
  - StudentExerciseSubmission.is_exercise_completed
  - StudentProblemSubmission  get_next_attempt_number, get_best_result,
                              get_best_points, has_solved, percentage, total_passed
  - ProblemSubmission         pass_rate, get_best_submission, has_passed
  - CodingTimeLog             reset_daily_if_needed, reset_weekly_if_needed
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.utils.timezone import localtime

from coding.models import (
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    CodingExercise,
    ProblemTestCase,
    ProblemSubmission,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    CodingTimeLog,
    calculate_coding_points,
)

User = get_user_model()


# ===========================================================================
# calculate_coding_points — edge cases
# ===========================================================================

class TestCalculateCodingPointsEdgeCases(TestCase):

    def test_zero_total_tests_returns_zero_not_division_error(self):
        """Guard clause: 0 total tests must return 0.0, not raise ZeroDivisionError."""
        self.assertEqual(calculate_coding_points(0, 0, 0), 0.0)
        self.assertEqual(calculate_coding_points(0, 0, 10), 0.0)

    def test_zero_passed_returns_zero(self):
        self.assertEqual(calculate_coding_points(0, 5, 10), 0.0)

    def test_zero_time_yields_maximum_for_full_pass(self):
        """k / (k + 0) == 1.0, so 5/5 at t=0 must equal exactly 100.0."""
        self.assertEqual(calculate_coding_points(5, 5, 0), 100.0)

    def test_quality_score_applied_as_multiplier(self):
        base = calculate_coding_points(5, 5, 0, quality_score=1.0)
        penalised = calculate_coding_points(5, 5, 0, quality_score=0.75)
        self.assertEqual(penalised, round(base * 0.75, 2))

    def test_quality_score_default_does_not_change_score(self):
        """quality_score defaults to 1.0 — omitting it must give the same result."""
        explicit = calculate_coding_points(5, 5, 1.0, quality_score=1.0)
        implicit = calculate_coding_points(5, 5, 1.0)
        self.assertEqual(explicit, implicit)

    def test_result_is_rounded_to_two_decimal_places(self):
        result = calculate_coding_points(1, 3, 7)
        self.assertEqual(result, round(result, 2))
        self.assertIsInstance(result, float)

    def test_longer_time_yields_lower_score(self):
        fast = calculate_coding_points(5, 5, 1)
        slow = calculate_coding_points(5, 5, 30)
        self.assertGreater(fast, slow)

    def test_partial_pass_proportional_to_accuracy(self):
        full = calculate_coding_points(5, 5, 0)
        half = calculate_coding_points(3, 5, 0, quality_score=1.0)
        self.assertAlmostEqual(half, round(full * (3 / 5), 2), places=1)


# ===========================================================================
# CodingLanguage — property tests (no DB required)
# ===========================================================================

class TestCodingLanguageProperties(TestCase):
    """Property tests that only need a CodingLanguage instance, not a DB row."""

    def _make(self, slug):
        lang = CodingLanguage.__new__(CodingLanguage)
        lang.slug = slug
        return lang

    # piston_language
    def test_piston_language_python(self):
        self.assertEqual(self._make('python').piston_language, 'python')

    def test_piston_language_javascript(self):
        self.assertEqual(self._make('javascript').piston_language, 'javascript')

    def test_piston_language_html_is_none(self):
        self.assertIsNone(self._make('html').piston_language)

    def test_piston_language_css_is_none(self):
        self.assertIsNone(self._make('css').piston_language)

    def test_piston_language_scratch_is_none(self):
        self.assertIsNone(self._make('scratch').piston_language)

    # uses_browser_sandbox
    def test_browser_sandbox_html(self):
        self.assertTrue(self._make('html').uses_browser_sandbox)

    def test_browser_sandbox_css(self):
        self.assertTrue(self._make('css').uses_browser_sandbox)

    def test_browser_sandbox_html_css_legacy(self):
        self.assertTrue(self._make('html-css').uses_browser_sandbox)

    def test_browser_sandbox_python_false(self):
        self.assertFalse(self._make('python').uses_browser_sandbox)

    def test_browser_sandbox_scratch_false(self):
        self.assertFalse(self._make('scratch').uses_browser_sandbox)

    # uses_scratch_vm
    def test_scratch_vm_scratch(self):
        self.assertTrue(self._make('scratch').uses_scratch_vm)

    def test_scratch_vm_python_false(self):
        self.assertFalse(self._make('python').uses_scratch_vm)

    def test_scratch_vm_javascript_false(self):
        self.assertFalse(self._make('javascript').uses_scratch_vm)


# ===========================================================================
# CodingProblem — property tests
# ===========================================================================

class TestCodingProblemProperties(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.lang,
            title='Test Problem',
            description='A test problem.',
            starter_code='',
            difficulty=1,
            is_active=True,
        )

    def test_visible_test_cases_returns_only_visible(self):
        ProblemTestCase.objects.create(
            problem=self.problem, input_data='a', expected_output='a',
            is_visible=True, display_order=1,
        )
        ProblemTestCase.objects.create(
            problem=self.problem, input_data='b', expected_output='b',
            is_visible=False, display_order=2,
        )
        self.assertEqual(self.problem.visible_test_cases.count(), 1)
        self.assertEqual(self.problem.visible_test_cases.first().input_data, 'a')

    def test_hidden_test_cases_returns_only_hidden(self):
        ProblemTestCase.objects.create(
            problem=self.problem, input_data='a', expected_output='a',
            is_visible=True, display_order=1,
        )
        ProblemTestCase.objects.create(
            problem=self.problem, input_data='b', expected_output='b',
            is_visible=False, display_order=2,
        )
        self.assertEqual(self.problem.hidden_test_cases.count(), 1)
        self.assertEqual(self.problem.hidden_test_cases.first().input_data, 'b')

    def test_total_test_cases_counts_all(self):
        for i in range(3):
            ProblemTestCase.objects.create(
                problem=self.problem, input_data=str(i),
                expected_output=str(i), display_order=i,
            )
        self.assertEqual(self.problem.total_test_cases, 3)

    def test_total_test_cases_zero_when_empty(self):
        self.assertEqual(self.problem.total_test_cases, 0)


# ===========================================================================
# StudentExerciseSubmission — class methods
# ===========================================================================

class TestStudentExerciseSubmission(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='ex_student', password='testpass123', email='ex_student@test.com',
        )
        cls.student2 = User.objects.create_user(
            username='ex_student2', password='testpass123', email='ex_student2@test.com',
        )
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.topic, _ = CodingTopic.objects.get_or_create(
            language=cls.lang, slug='ex-sub-variables',
            defaults={'name': 'Variables', 'order': 1, 'is_active': True},
        )
        cls.exercise = CodingExercise.objects.create(
            topic=cls.topic,
            level=CodingExercise.BEGINNER,
            title='Hello World',
            description='Print Hello, World!',
            starter_code='# Write your code here\n',
            expected_output='Hello, World!',
            order=1,
            is_active=True,
        )

    def test_is_completed_false_when_no_submission(self):
        self.assertFalse(
            StudentExerciseSubmission.is_exercise_completed(self.student, self.exercise)
        )

    def test_is_completed_false_when_incomplete_submission(self):
        StudentExerciseSubmission.objects.create(
            student=self.student,
            exercise=self.exercise,
            code_submitted='print("wrong")',
            is_completed=False,
        )
        self.assertFalse(
            StudentExerciseSubmission.is_exercise_completed(self.student, self.exercise)
        )

    def test_is_completed_true_after_completed_submission(self):
        StudentExerciseSubmission.objects.create(
            student=self.student,
            exercise=self.exercise,
            code_submitted='print("Hello, World!")',
            output_received='Hello, World!',
            is_completed=True,
            time_taken_seconds=30,
        )
        self.assertTrue(
            StudentExerciseSubmission.is_exercise_completed(self.student, self.exercise)
        )

    def test_is_completed_isolated_between_students(self):
        StudentExerciseSubmission.objects.create(
            student=self.student,
            exercise=self.exercise,
            code_submitted='print("hi")',
            is_completed=True,
        )
        self.assertFalse(
            StudentExerciseSubmission.is_exercise_completed(self.student2, self.exercise)
        )


# ===========================================================================
# StudentProblemSubmission — class methods and properties
# ===========================================================================

class TestStudentProblemSubmission(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='prob_student', password='testpass123', email='prob_student@test.com',
        )
        cls.student2 = User.objects.create_user(
            username='prob_student2', password='testpass123', email='prob_student2@test.com',
        )
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.lang,
            title='Reverse a String',
            description='Read a string and print it reversed.',
            starter_code='s = input()\n',
            difficulty=1,
            is_active=True,
        )

    # ── get_next_attempt_number ──────────────────────────────────────────────

    def test_first_attempt_is_one(self):
        self.assertEqual(
            StudentProblemSubmission.get_next_attempt_number(self.student, self.problem), 1
        )

    def test_second_attempt_is_two(self):
        StudentProblemSubmission.objects.create(
            student=self.student, problem=self.problem, attempt_number=1,
            code_submitted='pass', passed_all_tests=False,
        )
        self.assertEqual(
            StudentProblemSubmission.get_next_attempt_number(self.student, self.problem), 2
        )

    def test_attempt_number_isolated_per_student(self):
        StudentProblemSubmission.objects.create(
            student=self.student, problem=self.problem, attempt_number=1,
            code_submitted='pass', passed_all_tests=False,
        )
        self.assertEqual(
            StudentProblemSubmission.get_next_attempt_number(self.student2, self.problem), 1
        )

    # ── get_best_result ──────────────────────────────────────────────────────

    def test_get_best_result_none_when_no_submissions(self):
        self.assertIsNone(
            StudentProblemSubmission.get_best_result(self.student, self.problem)
        )

    def test_get_best_result_returns_highest_scoring(self):
        for attempt, pts in enumerate([70.0, 90.0, 80.0], start=1):
            StudentProblemSubmission.objects.create(
                student=self.student, problem=self.problem,
                attempt_number=attempt, code_submitted='pass',
                passed_all_tests=True, points=pts,
            )
        best = StudentProblemSubmission.get_best_result(self.student, self.problem)
        self.assertEqual(best.points, 90.0)

    # ── get_best_points ──────────────────────────────────────────────────────

    def test_get_best_points_zero_when_no_passing_submission(self):
        StudentProblemSubmission.objects.create(
            student=self.student, problem=self.problem, attempt_number=1,
            code_submitted='pass', passed_all_tests=False, points=0.0,
        )
        self.assertEqual(
            StudentProblemSubmission.get_best_points(self.student, self.problem), 0.0
        )

    def test_get_best_points_zero_when_no_submissions(self):
        self.assertEqual(
            StudentProblemSubmission.get_best_points(self.student, self.problem), 0.0
        )

    def test_get_best_points_returns_max_among_passing(self):
        for attempt, pts, passed in [
            (1, 80.0, True),
            (2, 95.0, True),
            (3, 85.0, True),
            (4, 0.0, False),    # failing submission — excluded from best
        ]:
            StudentProblemSubmission.objects.create(
                student=self.student, problem=self.problem,
                attempt_number=attempt, code_submitted='pass',
                passed_all_tests=passed, points=pts,
            )
        self.assertEqual(
            StudentProblemSubmission.get_best_points(self.student, self.problem), 95.0
        )

    # ── has_solved ───────────────────────────────────────────────────────────

    def test_has_solved_false_with_no_submissions(self):
        self.assertFalse(
            StudentProblemSubmission.has_solved(self.student, self.problem)
        )

    def test_has_solved_false_with_only_failing(self):
        StudentProblemSubmission.objects.create(
            student=self.student, problem=self.problem, attempt_number=1,
            code_submitted='print("wrong")', passed_all_tests=False,
            visible_passed=0, visible_total=1, hidden_passed=0, hidden_total=1,
            points=0.0, time_taken_seconds=20,
        )
        self.assertFalse(
            StudentProblemSubmission.has_solved(self.student, self.problem)
        )

    def test_has_solved_true_after_passing(self):
        StudentProblemSubmission.objects.create(
            student=self.student, problem=self.problem, attempt_number=1,
            code_submitted='s = input(); print(s[::-1])', passed_all_tests=True,
            visible_passed=1, visible_total=1, hidden_passed=1, hidden_total=1,
            points=85.5, time_taken_seconds=45,
        )
        self.assertTrue(
            StudentProblemSubmission.has_solved(self.student, self.problem)
        )

    # ── percentage & total_passed properties ─────────────────────────────────

    def test_percentage_zero_when_no_test_cases(self):
        sub = StudentProblemSubmission(
            student=self.student, problem=self.problem,
            visible_total=0, hidden_total=0,
            visible_passed=0, hidden_passed=0,
        )
        self.assertEqual(sub.percentage, 0)

    def test_percentage_calculated_correctly(self):
        sub = StudentProblemSubmission(
            student=self.student, problem=self.problem,
            visible_total=2, hidden_total=3,
            visible_passed=2, hidden_passed=2,
        )
        # 4 passed out of 5 total → 80 %
        self.assertEqual(sub.percentage, 80)

    def test_total_passed_sums_visible_and_hidden(self):
        sub = StudentProblemSubmission(
            student=self.student, problem=self.problem,
            visible_passed=3, hidden_passed=4,
            visible_total=3, hidden_total=5,
        )
        self.assertEqual(sub.total_passed, 7)

    def test_total_tests_sums_visible_and_hidden(self):
        sub = StudentProblemSubmission(
            student=self.student, problem=self.problem,
            visible_total=3, hidden_total=5,
        )
        self.assertEqual(sub.total_tests, 8)


# ===========================================================================
# ProblemSubmission — class methods and properties
# ===========================================================================

class TestProblemSubmissionModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='psub_student', password='testpass123', email='psub_student@test.com',
        )
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.lang,
            title='PS Test Problem',
            description='A problem for ProblemSubmission tests.',
            starter_code='',
            difficulty=2,
            is_active=True,
        )

    def test_pass_rate_zero_when_no_test_cases(self):
        sub = ProblemSubmission(
            student=self.student, problem=self.problem,
            submitted_code='pass',
            test_cases_passed=0, total_test_cases=0,
        )
        self.assertEqual(sub.pass_rate, 0)

    def test_pass_rate_rounds_correctly(self):
        sub = ProblemSubmission(
            student=self.student, problem=self.problem,
            submitted_code='pass',
            test_cases_passed=3, total_test_cases=4,
        )
        self.assertEqual(sub.pass_rate, 75)

    def test_get_best_submission_returns_highest_passed(self):
        ProblemSubmission.objects.create(
            student=self.student, problem=self.problem, submitted_code='p',
            status=ProblemSubmission.PASSED,
            test_cases_passed=3, total_test_cases=5,
        )
        ProblemSubmission.objects.create(
            student=self.student, problem=self.problem, submitted_code='p',
            status=ProblemSubmission.PASSED,
            test_cases_passed=5, total_test_cases=5,
        )
        best = ProblemSubmission.get_best_submission(self.student, self.problem)
        self.assertEqual(best.test_cases_passed, 5)

    def test_get_best_submission_none_when_empty(self):
        self.assertIsNone(
            ProblemSubmission.get_best_submission(self.student, self.problem)
        )

    def test_has_passed_false_with_only_failed_submissions(self):
        ProblemSubmission.objects.create(
            student=self.student, problem=self.problem, submitted_code='p',
            status=ProblemSubmission.FAILED,
            test_cases_passed=0, total_test_cases=2,
        )
        self.assertFalse(ProblemSubmission.has_passed(self.student, self.problem))

    def test_has_passed_true_after_passed_submission(self):
        ProblemSubmission.objects.create(
            student=self.student, problem=self.problem, submitted_code='p',
            status=ProblemSubmission.PASSED,
            test_cases_passed=2, total_test_cases=2,
        )
        self.assertTrue(ProblemSubmission.has_passed(self.student, self.problem))


# ===========================================================================
# CodingTimeLog — reset logic
# ===========================================================================

class TestCodingTimeLogResets(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='timelog_student', password='testpass123',
            email='timelog_student@test.com',
        )

    def test_reset_daily_triggers_on_new_day(self):
        """reset_daily_if_needed() must zero daily_total_seconds when date changes."""
        log = CodingTimeLog.objects.create(
            student=self.student,
            daily_total_seconds=500,
            weekly_total_seconds=2000,
        )
        yesterday = timezone.now().date() - datetime.timedelta(days=1)
        CodingTimeLog.objects.filter(pk=log.pk).update(last_reset_date=yesterday)
        log.refresh_from_db()

        log.reset_daily_if_needed()

        log.refresh_from_db()
        self.assertEqual(log.daily_total_seconds, 0)
        self.assertEqual(log.weekly_total_seconds, 2000)   # weekly must be unchanged

    def test_reset_daily_no_op_on_same_day(self):
        """reset_daily_if_needed() must do nothing when last_reset_date == today."""
        log = CodingTimeLog.objects.create(
            student=self.student,
            daily_total_seconds=300,
        )
        log.reset_daily_if_needed()
        self.assertEqual(log.daily_total_seconds, 300)

    def test_reset_weekly_triggers_on_new_iso_week(self):
        """reset_weekly_if_needed() must zero weekly_total_seconds when ISO week changes."""
        log = CodingTimeLog.objects.create(
            student=self.student,
            daily_total_seconds=100,
            weekly_total_seconds=5000,
            last_reset_week=1,    # ISO week 1 of year 1 — guaranteed to be in the past
        )
        log.reset_weekly_if_needed()

        log.refresh_from_db()
        self.assertEqual(log.weekly_total_seconds, 0)
        self.assertEqual(log.daily_total_seconds, 100)    # daily must be unchanged

    def test_reset_weekly_no_op_on_same_iso_week(self):
        """reset_weekly_if_needed() must do nothing within the same ISO week."""
        current_week = localtime(timezone.now()).isocalendar()[1]
        log = CodingTimeLog.objects.create(
            student=self.student,
            weekly_total_seconds=800,
            last_reset_week=current_week,
        )
        log.reset_weekly_if_needed()
        self.assertEqual(log.weekly_total_seconds, 800)
