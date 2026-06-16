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

    # ── long-multiplication partial-product working rows ───────────────────────
    def _shifts_and_boxes(self, ca):
        """(shift, box-count) per partial row, for terse assertions."""
        return [(p['shift'], len(list(p['boxes']))) for p in ca['partials']]

    def test_partials_two_digit_multiplier(self):
        # 23 × 64 = 1472 (width 4). One row per multiplier digit: ×4 at the units
        # (shift 0, 4 boxes), ×6 at the tens (shift 1, 3 boxes + 1 spacer).
        ca = self._q([23, 64], '*').column_arithmetic
        self.assertEqual(self._shifts_and_boxes(ca), [(0, 4), (1, 3)])
        self.assertEqual([len(list(p['spacers'])) for p in ca['partials']], [0, 1])

    def test_partials_skip_zero_digit(self):
        # 23 × 101 = 2323 (width 4). The tens digit is 0 → no row; the next
        # non-zero digit (hundreds) shifts by its full place value (2), not 1.
        ca = self._q([23, 101], '*').column_arithmetic
        self.assertEqual(self._shifts_and_boxes(ca), [(0, 4), (2, 2)])

    def test_no_partials_single_significant_digit(self):
        # A multiplier with one non-zero digit needs no partials — the simple
        # single-answer-row layout is kept (×4, ×10, ×100, ×60, ×500).
        for multiplier in (4, 10, 100, 60, 500):
            ca = self._q([23, multiplier], '*').column_arithmetic
            self.assertNotIn('partials', ca, f'×{multiplier} should have no partials')

    def test_no_partials_three_operands(self):
        # Long multiplication is only defined for two operands.
        self.assertNotIn('partials', self._q([12, 12, 12], '*').column_arithmetic)

    def test_no_partials_addition_subtraction(self):
        self.assertNotIn('partials', self._q([90, 82], '+').column_arithmetic)
        self.assertNotIn('partials', self._q([90, 82], '-').column_arithmetic)

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

    def test_long_multiplication_grades_on_final_answer_only(self):
        # The partial-product rows are scratch space; grading still compares only
        # the final answer against column_result.
        q = self._save([23, 64], '*')
        self.assertTrue(self._grade(q, '1472')['is_correct'])
        self.assertFalse(self._grade(q, '92')['is_correct'])  # a partial, not the total


class ColumnArithmeticTemplateRenderTests(TestCase):
    """Render the worksheet column-operation partial and assert the long-
    multiplication working rows appear in the HTML (and don't, when they
    shouldn't). The partial scratch cells must carry no `data-ca-answer`
    attribute so the answer-sync JS — and thus grading — ignores them."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=995, defaults={'display_name': 'column render fixture'},
        )

    def _render(self, operands, operator):
        from django.template.loader import render_to_string
        q = Question(
            level=self.level,
            question_text='Multiply.',
            question_type=Question.COLUMN_OPERATION,
            operands=operands,
            operator=operator,
            difficulty=1,
            points=1,
        )
        return render_to_string(
            'worksheets/partials/_answer_column_operation.html', {'question': q},
        )

    # aria-label is unique to the input cells; `data-ca-answer` also appears as a
    # selector string inside the partial's <script>, so count by aria-label.
    _PARTIAL = 'aria-label="partial product working digit"'
    _ANSWER = 'aria-label="answer digit column'

    def test_long_multiplication_renders_partial_rows(self):
        html = self._render([23, 64], '*')
        # 23×64 → 2 partial rows = 4 + 3 = 7 amber scratch boxes, none of which
        # are graded answer cells.
        self.assertEqual(html.count(self._PARTIAL), 7)
        # The blue final-answer row is still present (width 4).
        self.assertEqual(html.count(self._ANSWER), 4)

    def test_single_digit_multiplier_has_no_partial_rows(self):
        html = self._render([23, 4], '*')
        self.assertNotIn(self._PARTIAL, html)
        self.assertEqual(html.count(self._ANSWER), 2)  # 23×4 = 92, width 2
