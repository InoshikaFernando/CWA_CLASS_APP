"""Render tests for the shape_select take-item partial.

Covers the ``shape_select_data`` model property, the pure ``shape_select_svg``
builder, and the homework take-item partial branch (tappable SVG shapes +
hidden JSON input). The tap-to-colour interaction itself is covered by the
Playwright test in ui_tests/test_shape_select.py. Mirrors
test_draw_on_grid_render.py.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.models import Question
from maths.svg_geometry import shape_select_svg


def _spec():
    return {
        'target_type': 'triangle',
        'viewbox': [680, 400],
        'shapes': [
            {'id': 's0', 'type': 'triangle', 'cx': 60, 'cy': 60, 'size': 30, 'rot': 12},
            {'id': 's1', 'type': 'circle', 'cx': 200, 'cy': 60, 'size': 28, 'rot': 0},
            {'id': 's2', 'type': 'rectangle', 'cx': 360, 'cy': 60, 'size': 26, 'rot': -8},
        ],
    }


class ShapeSelectSvgBuilderTests(TestCase):
    def test_emits_one_element_per_shape_with_data_attrs(self):
        svg = shape_select_svg(_spec())
        self.assertIn('data-shape-id="s0"', svg)
        self.assertIn('data-shape-type="triangle"', svg)
        self.assertIn('<polygon', svg)   # triangle
        self.assertIn('<circle', svg)    # circle
        self.assertIn('<rect', svg)      # rectangle
        self.assertEqual(svg.count('class="cwa-shape"'), 3)

    def test_empty_for_malformed_spec(self):
        self.assertEqual(shape_select_svg(None), '')
        self.assertEqual(shape_select_svg({'shapes': []}), '')

    def test_skips_malformed_shape_without_500(self):
        # A shape that bypassed validate_shape_spec is dropped, not fatal.
        spec = _spec()
        spec['shapes'].append({'id': 's9', 'type': 'triangle', 'cx': 'x', 'cy': 1, 'size': 5})
        svg = shape_select_svg(spec)
        self.assertEqual(svg.count('class="cwa-shape"'), 3)   # bad one skipped


class ShapeSelectDataPropertyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=980, defaults={'display_name': 'ss render fixture'},
        )

    def _q(self, **over):
        fields = dict(
            level=self.level, question_text='Colour all the triangles.',
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
            shape_spec=_spec(),
        )
        fields.update(over)
        return Question(**fields)

    def test_data_carries_dimensions_and_svg(self):
        data = self._q().shape_select_data
        self.assertEqual((data['width'], data['height']), (680, 400))
        self.assertEqual(data['target_type'], 'triangle')
        self.assertIn('data-shape-id="s0"', data['svg'])

    def test_data_none_for_other_types(self):
        self.assertIsNone(
            self._q(question_type=Question.MULTIPLE_CHOICE, shape_spec=None).shape_select_data
        )


class ShapeSelectPartialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=979, defaults={'display_name': 'ss partial fixture'},
        )

    def test_partial_renders_shapes_and_hidden_input(self):
        q = Question.objects.create(
            level=self.level, question_text='Colour all the triangles.',
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
            shape_spec=_spec(),
        )
        html = render_to_string(
            'homework/partials/_maths_take_item.html',
            {'ctx': {'question': q, 'shuffled_answers': []}},
        )
        self.assertIn('<svg', html)
        self.assertIn(f'data-ss-hidden="{q.id}"', html)   # hidden JSON input
        self.assertIn('class="cwa-shape"', html)          # tappable shapes
        self.assertIn(f'name="answer_{q.id}"', html)
        self.assertNotIn('type="radio"', html)            # not an MCQ
