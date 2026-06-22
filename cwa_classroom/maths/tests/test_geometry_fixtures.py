"""Tests for the seeded geometry/measurement starter questions (CPP-340).

Exercises ``maths.seed_geometry.seed`` directly (creating the Mathematics
subject + a Year-6 level first), which is exactly what the 0032 data migration
runs. Asserts the seeded questions validate and grade correctly, and that the
seed is idempotent. Epic CPP-330.
"""
import json

from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.geometry_grading import (
    grade_draw_on_grid,
    grade_measure,
    validate_grid_spec,
)
from maths.models import Answer, Question
from maths.seed_geometry import (
    MEASURE_TEXT,
    SYMMETRY_GRID_SPEC,
    SYMMETRY_TEXT,
    seed,
)


class GeometrySeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Subject.objects.get_or_create(
            name='Mathematics', school=None,
            defaults={'slug': 'mathematics', 'is_active': True},
        )
        Level.objects.get_or_create(
            level_number=6, defaults={'display_name': 'Year 6'},
        )
        seed(Subject, Level, Topic, Question, Answer)

    def test_symmetry_fixture_loads_and_validates(self):
        q = Question.objects.get(
            question_type='draw_on_grid', question_text=SYMMETRY_TEXT,
        )
        validate_grid_spec(q.grid_spec)  # must not raise
        # A submission of exactly the target segments grades correct.
        payload = json.dumps({'segments': SYMMETRY_GRID_SPEC['target']['segments']})
        self.assertTrue(grade_draw_on_grid(q.grid_spec, payload))
        # The question carries no answer options (graded by the marks).
        self.assertFalse(q.answers.exists())

    def test_measure_fixture_grades_correct_answer(self):
        q = Question.objects.get(question_type='measure', question_text=MEASURE_TEXT)
        self.assertTrue(grade_measure(q, '135'))   # exact
        self.assertTrue(grade_measure(q, '134'))   # within ±2
        self.assertFalse(grade_measure(q, '120'))  # outside

    def test_seeded_questions_are_global(self):
        for text in (SYMMETRY_TEXT, MEASURE_TEXT):
            self.assertIsNone(Question.objects.get(question_text=text).school)

    def test_seed_is_idempotent(self):
        # Running the seed again must not create duplicates.
        seed(Subject, Level, Topic, Question, Answer)
        self.assertEqual(Question.objects.filter(question_text=SYMMETRY_TEXT).count(), 1)
        self.assertEqual(Question.objects.filter(question_text=MEASURE_TEXT).count(), 1)

    def test_seed_noop_without_maths_subject(self):
        # No global Mathematics subject → nothing seeded, no error.
        Question.objects.all().delete()
        Subject.objects.filter(name='Mathematics', school__isnull=True).delete()
        seed(Subject, Level, Topic, Question, Answer)
        self.assertEqual(Question.objects.filter(question_text=SYMMETRY_TEXT).count(), 0)
