"""The homework 'take' partial renders column_operation as a stacked grid.

Regression: column_operation previously fell through to the generic short-answer
box (inline "14 + 73 =" + a text input). Students should instead get the
vertical column-arithmetic widget with per-digit answer cells, like the quiz.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.models import Question


class ColumnArithmeticTakeRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=995, defaults={'display_name': 'ca render fixture'},
        )

    def _render(self, operands, operator):
        q = Question.objects.create(
            level=self.level,
            question_text='Find the sum.',
            question_type=Question.COLUMN_OPERATION,
            operands=operands, operator=operator, difficulty=1, points=1,
        )
        return render_to_string(
            'homework/partials/_maths_take_item.html', {'ctx': {'question': q}}
        )

    def test_renders_stacked_widget_not_generic_input(self):
        html = self._render([14, 73], '+')
        # Stacked widget markers present
        self.assertIn('data-ca-wrap="', html)
        self.assertIn('data-ca-answer="', html)
        self.assertIn('data-ca-hidden="', html)
        # The single hidden field carries the answer
        self.assertIn('name="answer_', html)
        # Generic "type your answer" fallback should NOT be used for this type
        self.assertNotIn('Type your answer...', html)

    def test_answer_cell_count_matches_grid_width(self):
        # One answer <input> per grid column — count the per-cell aria-label,
        # which (unlike the data-ca-answer attribute) does not also appear in the JS.
        marker = 'aria-label="answer digit column'
        # 14 + 73 = 87 → 2-digit result → 2 answer columns
        self.assertEqual(self._render([14, 73], '+').count(marker), 2)
        # 91 + 12 = 103 → 3-digit result → 3 answer columns (grid widens)
        self.assertEqual(self._render([91, 12], '+').count(marker), 3)
