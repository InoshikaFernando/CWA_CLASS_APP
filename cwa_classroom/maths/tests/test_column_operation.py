"""Column-arithmetic question type (vertical/stacked + - ×).

Covers the computed-answer and render-structure properties on Question, which
the import path and the quiz template both rely on.
"""
from django.test import TestCase

from classroom.models import Level
from maths.models import Question


class ColumnArithmeticPropertyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993, defaults={'display_name': 'column fixture'},
        )

    def _q(self, operands, operator):
        return Question(
            level=self.level,
            question_text='Find the difference.',
            question_type=Question.COLUMN_OPERATION,
            operands=operands,
            operator=operator,
            difficulty=1,
            points=1,
        )

    # ── column_result ────────────────────────────────────────────────────────
    def test_result_subtraction(self):
        self.assertEqual(self._q([90, 82], '-').column_result, 8)

    def test_result_addition(self):
        self.assertEqual(self._q([90, 82], '+').column_result, 172)

    def test_result_multiplication(self):
        self.assertEqual(self._q([12, 12], '*').column_result, 144)

    def test_result_chained_subtraction_is_left_fold(self):
        self.assertEqual(self._q([100, 30, 20], '-').column_result, 50)

    def test_result_none_when_incomplete(self):
        self.assertIsNone(self._q([], '-').column_result)
        self.assertIsNone(self._q([90, 82], '').column_result)

    # ── column_arithmetic render structure ─────────────────────────────────────
    def test_structure_subtraction_no_widening(self):
        ca = self._q([90, 82], '-').column_arithmetic
        self.assertEqual(ca['width'], 2)
        self.assertEqual(ca['rows'], [['9', '0'], ['8', '2']])
        self.assertEqual(ca['operator'], '−')  # display minus sign
        self.assertEqual(list(ca['cols']), [0, 1])

    def test_structure_addition_widens_and_left_pads(self):
        # 90 + 82 = 172 → answer is 3 digits, so the grid is 3 columns wide and
        # the 2-digit operands are left-padded with a blank.
        ca = self._q([90, 82], '+').column_arithmetic
        self.assertEqual(ca['width'], 3)
        self.assertEqual(ca['rows'], [['', '9', '0'], ['', '8', '2']])
        self.assertEqual(ca['operator'], '+')

    def test_structure_multiplication_symbol(self):
        self.assertEqual(self._q([12, 12], '*').column_arithmetic['operator'], '×')

    def test_structure_none_when_invalid(self):
        self.assertIsNone(self._q([], '+').column_arithmetic)       # no operands
        self.assertIsNone(self._q([5, 5], 'bad').column_arithmetic)  # unknown operator

    # ── column_inline (fallback for non-grid renderers) ────────────────────────
    def test_inline_uses_display_operator(self):
        self.assertEqual(self._q([90, 82], '-').column_inline, '90 − 82')
        self.assertEqual(self._q([90, 82], '+').column_inline, '90 + 82')
        self.assertEqual(self._q([12, 12], '*').column_inline, '12 × 12')
        self.assertEqual(self._q([100, 30, 20], '-').column_inline, '100 − 30 − 20')

    def test_inline_empty_when_invalid(self):
        self.assertEqual(self._q([5, 5], 'bad').column_inline, '')


class ColumnArithmeticGradingTests(TestCase):
    """The plugin grades column_operation against the computed result, so a
    question grades itself even without a stored answer row."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=994, defaults={'display_name': 'column grading fixture'},
        )

    def _save(self, operands, operator):
        return Question.objects.create(
            level=self.level,
            question_text='Find the sum.',
            question_type=Question.COLUMN_OPERATION,
            operands=operands,
            operator=operator,
            difficulty=1,
            points=1,
        )

    def _grade(self, q, answer):
        from maths.plugin import MathsPlugin
        return MathsPlugin().grade_answer(q.pk, {f'answer_{q.id}': answer})

    def test_correct_answer_grades_true_without_answer_row(self):
        q = self._save([23, 25], '+')
        result = self._grade(q, '48')
        self.assertTrue(result['is_correct'])
        self.assertEqual(result['points_earned'], q.points)

    def test_leading_zeros_and_spaces_tolerated(self):
        q = self._save([23, 25], '+')
        self.assertTrue(self._grade(q, ' 048 ')['is_correct'])

    def test_wrong_answer_grades_false(self):
        q = self._save([23, 25], '+')
        self.assertFalse(self._grade(q, '47')['is_correct'])

    def test_subtraction_and_multiplication(self):
        self.assertTrue(self._grade(self._save([68, 20], '-'), '48')['is_correct'])
        self.assertTrue(self._grade(self._save([12, 12], '*'), '144')['is_correct'])

    def test_non_numeric_answer_grades_false(self):
        q = self._save([23, 25], '+')
        self.assertFalse(self._grade(q, 'forty-eight')['is_correct'])
