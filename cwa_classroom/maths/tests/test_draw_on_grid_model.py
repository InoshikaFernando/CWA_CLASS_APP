"""Tests for the ``draw_on_grid`` question type model (CPP-336).

The model layer only adds the type + a ``grid_spec`` JSONField; schema
validation is CPP-338 and grading is CPP-337. Epic CPP-330.
"""
from django.test import TestCase

from classroom.models import Level
from maths.models import Question


class DrawOnGridModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=987, defaults={'display_name': 'draw_on_grid fixture'},
        )

    def test_draw_on_grid_type_constant_and_choice(self):
        self.assertEqual(Question.DRAW_ON_GRID, 'draw_on_grid')
        self.assertIn(
            ('draw_on_grid', 'Draw on Grid (symmetry / reflection / plot)'),
            Question.QUESTION_TYPES,
        )

    def test_grid_spec_roundtrips_json(self):
        spec = {
            'grid': {'cols': 11, 'rows': 9},
            'shape': {'type': 'polygon', 'points': [[2, 3], [5, 2], [5, 5], [2, 5]]},
            'mode': 'segments',
            'target': {'segments': [{'x1': 4, 'y1': 0, 'x2': 4, 'y2': 8}]},
            'allow_extra': False,
        }
        q = Question.objects.create(
            level=self.level,
            question_text='Draw all lines of symmetry.',
            question_type=Question.DRAW_ON_GRID,
            difficulty=1, points=1,
            grid_spec=spec,
        )
        q.refresh_from_db()
        self.assertEqual(q.grid_spec, spec)
        # Nested structures survive the JSON round-trip.
        self.assertEqual(q.grid_spec['target']['segments'][0]['x1'], 4)

    def test_grid_spec_defaults_null_for_other_types(self):
        q = Question.objects.create(
            level=self.level, question_text='2+2?',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1,
        )
        q.refresh_from_db()
        self.assertIsNone(q.grid_spec)
