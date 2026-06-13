"""Rendering/authoring tests for the measure question type (CPP-334).

Covers the ``measure_figure_svg`` model property, the take-item partial
branch (figure + unit-suffixed input), and the admin readonly figure
preview. Epic CPP-330.
"""
from decimal import Decimal

from django.contrib.admin.sites import site
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.admin import QuestionAdmin
from maths.models import Question


class MeasureFigureSvgPropertyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992, defaults={'display_name': 'measure render fixture'},
        )

    def _measure(self, **over):
        fields = dict(
            level=self.level, question_text='Measure angle a.',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('135'), answer_tolerance=Decimal('2'),
            answer_unit='°',
        )
        fields.update(over)
        return Question(**fields)

    def test_property_returns_svg_for_measure(self):
        svg = self._measure().measure_figure_svg
        self.assertTrue(svg.startswith('<svg'))
        self.assertIn('viewBox', svg)

    def test_property_empty_without_value(self):
        self.assertEqual(self._measure(numeric_answer=None).measure_figure_svg, '')

    def test_property_empty_for_other_types(self):
        q = self._measure(question_type=Question.MULTIPLE_CHOICE)
        self.assertEqual(q.measure_figure_svg, '')


class MeasureTakeItemPartialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=991, defaults={'display_name': 'measure partial fixture'},
        )

    def test_partial_renders_figure_input_and_unit(self):
        q = Question.objects.create(
            level=self.level, question_text='Measure angle a.',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('135'), answer_tolerance=Decimal('2'),
            answer_unit='°',
        )
        html = render_to_string(
            'homework/partials/_maths_take_item.html',
            {'ctx': {'question': q, 'shuffled_answers': []}},
        )
        self.assertIn('<svg', html)                      # generated figure
        self.assertIn(f'name="answer_{q.id}"', html)     # the numeric input
        self.assertIn('°', html)                         # unit suffix
        self.assertNotIn('type="radio"', html)           # not rendered as MCQ


class MeasureAdminPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=990, defaults={'display_name': 'measure admin fixture'},
        )

    def test_preview_renders_svg_for_measure(self):
        q = Question(
            level=self.level, question_text='Measure angle a.',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('135'), answer_unit='°',
        )
        out = QuestionAdmin(Question, site).measure_figure_preview(q)
        self.assertIn('<svg', out)

    def test_preview_message_when_not_measure(self):
        q = Question(
            level=self.level, question_text='2+2?',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1,
        )
        out = QuestionAdmin(Question, site).measure_figure_preview(q)
        self.assertNotIn('<svg', out)
        self.assertIn('measure', out.lower())
