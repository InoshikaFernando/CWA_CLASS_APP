"""Tests for the ``measure`` question type (CPP-331).

Logic tests of the model: the ``measure`` constant/choice, the
``Question.clean()`` branch that requires a ``numeric_answer`` and forbids
answer options, null-tolerance handling, and Decimal precision on the
``numeric_answer`` / ``answer_tolerance`` columns.

Mirrors the in-memory ``clean()`` testing style of ``test_question_clean.py``
— construct Question instances and assert ``full_clean()`` raises (or not).
Epic CPP-330; spec docs/specs/CPP-330_interactive_geometry_questions.md.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question


class MeasureQuestionTypeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=994,
            defaults={'display_name': 'measure type fixture'},
        )

    def _build(self, **overrides):
        """In-memory measure Question; override any field via kwargs."""
        fields = dict(
            level=self.level,
            question_text='Measure angle a.',
            question_type=Question.MEASURE,
            difficulty=1,
            points=1,
            numeric_answer=Decimal('135'),
            answer_tolerance=Decimal('2'),
            answer_unit='°',
        )
        fields.update(overrides)
        return Question(**fields)

    # ── type registration ────────────────────────────────────────────────

    def test_measure_type_constant_and_choice(self):
        self.assertEqual(Question.MEASURE, 'measure')
        self.assertIn(
            ('measure', 'Measure (angle/scale, tolerance-graded)'),
            Question.QUESTION_TYPES,
        )

    # ── clean(): numeric_answer required ─────────────────────────────────

    def test_measure_requires_numeric_answer(self):
        q = self._build(numeric_answer=None)
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('numeric_answer', ctx.exception.error_dict)

    def test_measure_allows_null_tolerance(self):
        # NULL tolerance is valid — it means "exact match" at grade time.
        q = self._build(answer_tolerance=None)
        q.full_clean()  # must not raise

    # ── clean(): no answer options on a measure question ─────────────────

    def test_measure_rejects_answer_rows(self):
        q = self._build()
        q.save()
        Answer.objects.create(question=q, answer_text='135', is_correct=True)
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('question_type', ctx.exception.error_dict)

    # ── no regression for other types ────────────────────────────────────

    def test_non_measure_unaffected(self):
        # An ordinary MCQ has no numeric_answer and may carry Answer rows;
        # the measure branch must not touch it.
        q = Question(
            level=self.level,
            question_text='2 + 2 = ?',
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=1,
            points=1,
        )
        q.save()
        Answer.objects.create(question=q, answer_text='4', is_correct=True)
        q.full_clean()  # must not raise

    # ── Decimal precision (never float) ──────────────────────────────────

    def test_decimal_precision_preserved(self):
        q = self._build(
            numeric_answer=Decimal('135.500'),
            answer_tolerance=Decimal('2.500'),
        )
        q.save()
        q.refresh_from_db()
        self.assertEqual(q.numeric_answer, Decimal('135.500'))
        self.assertEqual(q.answer_tolerance, Decimal('2.500'))
