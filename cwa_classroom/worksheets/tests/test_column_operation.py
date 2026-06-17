"""Column-arithmetic (column_operation) support in the worksheet student session.

Students answering a worksheet should get the stacked vertical grid (like the
homework take page and the printable worksheet), and the answer should grade
against the computed column_result without needing a stored answer row.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.models import Question
from worksheets.views import (
    ANSWER_PARTIAL_MAP,
    _ANSWER_PARTIAL_DEFAULT,
    _grade_column_operation,
)


class ColumnOperationPartialDispatchTests(TestCase):
    def test_column_operation_maps_to_stacked_partial(self):
        self.assertEqual(
            ANSWER_PARTIAL_MAP.get('column_operation', _ANSWER_PARTIAL_DEFAULT),
            'worksheets/partials/_answer_column_operation.html',
        )
        # Regression guard: it must NOT fall back to the plain text box.
        self.assertNotEqual(
            ANSWER_PARTIAL_MAP.get('column_operation'), _ANSWER_PARTIAL_DEFAULT,
        )


class ColumnOperationGradingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=996, defaults={'display_name': 'ws ca fixture'},
        )

    def _q(self, operands, operator):
        return Question.objects.create(
            level=self.level, question_text='Find the sum.',
            question_type=Question.COLUMN_OPERATION,
            operands=operands, operator=operator, difficulty=1, points=1,
        )

    def test_correct_addition(self):
        self.assertTrue(_grade_column_operation(self._q([23, 25], '+'), '48'))

    def test_leading_zeros_and_spaces_tolerated(self):
        self.assertTrue(_grade_column_operation(self._q([23, 25], '+'), ' 048 '))

    def test_wrong_answer(self):
        self.assertFalse(_grade_column_operation(self._q([23, 25], '+'), '47'))

    def test_subtraction_and_multiplication(self):
        self.assertTrue(_grade_column_operation(self._q([68, 20], '-'), '48'))
        self.assertTrue(_grade_column_operation(self._q([12, 12], '*'), '144'))

    def test_non_numeric_is_false(self):
        self.assertFalse(_grade_column_operation(self._q([23, 25], '+'), 'forty-eight'))

    def test_blank_is_false(self):
        self.assertFalse(_grade_column_operation(self._q([23, 25], '+'), ''))


class ColumnOperationRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=997, defaults={'display_name': 'ws ca render fixture'},
        )

    def _render(self, operands, operator):
        q = Question.objects.create(
            level=self.level, question_text='Find the sum.',
            question_type=Question.COLUMN_OPERATION,
            operands=operands, operator=operator, difficulty=1, points=1,
        )
        return render_to_string(
            'worksheets/partials/_answer_column_operation.html', {'question': q},
        )

    def test_renders_stacked_grid_with_hidden_text_answer(self):
        html = self._render([14, 73], '+')
        self.assertIn('data-ca-wrap="', html)
        self.assertIn('data-ca-answer="', html)
        # Worksheet session posts the answer via a hidden field named text_answer.
        self.assertIn('name="text_answer"', html)

    def test_answer_cell_count_tracks_grid_width(self):
        marker = 'aria-label="answer digit column'
        self.assertEqual(self._render([14, 73], '+').count(marker), 2)   # 87 → 2 cols
        self.assertEqual(self._render([91, 12], '+').count(marker), 3)   # 103 → 3 cols
