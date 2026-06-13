"""Render tests for the draw_on_grid take-item partial (CPP-339).

Covers the ``draw_on_grid_data`` model property and the homework take-item
partial branch (grid SVG + clickable dots + hidden JSON input). The
click-to-draw interaction itself is covered by the Playwright test in
ui_tests/test_draw_on_grid.py. Epic CPP-330.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.models import Question


def _spec():
    return {
        'grid': {'cols': 9, 'rows': 9},
        'shape': {'type': 'polygon', 'points': [[2, 3], [6, 3], [6, 5], [2, 5]]},
        'mode': 'segments',
        'target': {'segments': [{'x1': 4, 'y1': 0, 'x2': 4, 'y2': 8}]},
        'allow_extra': False,
    }


class DrawOnGridDataPropertyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=984, defaults={'display_name': 'dog render fixture'},
        )

    def _q(self, **over):
        fields = dict(
            level=self.level, question_text='Draw all lines of symmetry.',
            question_type=Question.DRAW_ON_GRID, difficulty=1, points=1,
            grid_spec=_spec(),
        )
        fields.update(over)
        return Question(**fields)

    def test_data_has_one_dot_per_grid_cell(self):
        data = self._q().draw_on_grid_data
        self.assertEqual(len(data['dots']), 9 * 9)
        self.assertEqual((data['cols'], data['rows']), (9, 9))

    def test_data_maps_grid_to_pixels(self):
        data = self._q().draw_on_grid_data
        # Dot (0,0) sits at the pad offset; spacing is one step.
        first = next(d for d in data['dots'] if d['gx'] == 0 and d['gy'] == 0)
        self.assertEqual((first['px'], first['py']), (data['pad'], data['pad']))
        self.assertTrue(data['polygon'])  # shape rendered

    def test_data_none_for_other_types(self):
        self.assertIsNone(self._q(question_type=Question.MULTIPLE_CHOICE,
                                  grid_spec=None).draw_on_grid_data)


class DrawOnGridPartialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=983, defaults={'display_name': 'dog partial fixture'},
        )

    def test_partial_renders_grid_dots_and_hidden_input(self):
        q = Question.objects.create(
            level=self.level, question_text='Draw all lines of symmetry.',
            question_type=Question.DRAW_ON_GRID, difficulty=1, points=1,
            grid_spec=_spec(),
        )
        html = render_to_string(
            'homework/partials/_maths_take_item.html',
            {'ctx': {'question': q, 'shuffled_answers': []}},
        )
        self.assertIn('<svg', html)
        self.assertIn(f'data-dog-hidden="{q.id}"', html)   # hidden JSON input
        self.assertIn('data-gx=', html)                    # clickable dots carry grid coords
        self.assertIn(f'name="answer_{q.id}"', html)
        self.assertNotIn('type="radio"', html)             # not an MCQ
