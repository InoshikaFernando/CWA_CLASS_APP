"""Tests for the ``shape_select`` question type model.

Covers the type constant + choice, the ``shape_spec`` JSONField round-trip, and
the ``clean()`` validation branch (requires a spec, rejects answer options,
rejects a malformed spec). Mirrors test_draw_on_grid_model.py.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question


def _spec():
    return {
        'target_type': 'triangle',
        'viewbox': [680, 400],
        'shapes': [
            {'id': 's0', 'type': 'triangle', 'cx': 60, 'cy': 60, 'size': 30, 'rot': 0},
            {'id': 's1', 'type': 'circle', 'cx': 200, 'cy': 60, 'size': 28, 'rot': 0},
        ],
    }


class ShapeSelectModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=981, defaults={'display_name': 'shape_select fixture'},
        )

    def test_type_constant_and_choice(self):
        self.assertEqual(Question.SHAPE_SELECT, 'shape_select')
        self.assertIn(
            ('shape_select', 'Shape Select (find & colour shapes)'),
            Question.QUESTION_TYPES,
        )

    def test_shape_spec_roundtrips_json(self):
        q = Question.objects.create(
            level=self.level, question_text='Colour all the triangles.',
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
            shape_spec=_spec(),
        )
        q.refresh_from_db()
        self.assertEqual(q.shape_spec['target_type'], 'triangle')
        self.assertEqual(q.shape_spec['shapes'][0]['type'], 'triangle')

    def test_shape_spec_defaults_null_for_other_types(self):
        q = Question.objects.create(
            level=self.level, question_text='2+2?',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1,
        )
        q.refresh_from_db()
        self.assertIsNone(q.shape_spec)

    def test_clean_requires_shape_spec(self):
        q = Question(
            level=self.level, question_text='Colour all the triangles.',
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
        )
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('shape_spec', ctx.exception.error_dict)

    def test_clean_rejects_malformed_spec(self):
        q = Question(
            level=self.level, question_text='Colour all the triangles.',
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
            shape_spec={'target_type': 'triangle', 'shapes': []},
        )
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('shape_spec', ctx.exception.error_dict)

    def test_clean_rejects_answer_options(self):
        q = Question.objects.create(
            level=self.level, question_text='Colour all the triangles.',
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
            shape_spec=_spec(),
        )
        Answer.objects.create(question=q, answer_text='nope', is_correct=True)
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('question_type', ctx.exception.error_dict)
