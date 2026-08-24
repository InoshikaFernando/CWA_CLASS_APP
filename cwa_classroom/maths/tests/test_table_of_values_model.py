"""Model + plugin-dispatch tests for the ``table_of_values`` question type.

The type constant/choice, the ``Question.clean()`` branch that requires a valid
``table_spec`` and forbids answer options, the ``table_data`` render helper, and
the maths-plugin grading dispatch (homework take surface). Mirrors
``test_number_line_model``.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question
from maths.plugin import MathsPlugin


class TableOfValuesModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=991, defaults={'display_name': 'table_of_values fixture'})

    def _build(self, **overrides):
        fields = dict(
            level=self.level,
            question_text='Complete the table for y = x² - 2.',
            question_type=Question.TABLE_OF_VALUES,
            difficulty=1,
            points=1,
            table_spec={
                'headers': ['x', 'y'],
                'rows': [
                    [{'given': '-1'}, {'answer': '-1'}],
                    [{'given': '0'}, {'answer': '-2'}],
                    [{'given': '2'}, {'answer': '2'}],
                ],
            },
        )
        fields.update(overrides)
        return Question(**fields)

    # ── type registration ────────────────────────────────────────────────

    def test_type_constant_and_choice(self):
        self.assertEqual(Question.TABLE_OF_VALUES, 'table_of_values')
        self.assertIn(
            ('table_of_values', 'Table of Values (fill in the x/y table)'),
            Question.QUESTION_TYPES,
        )

    # ── clean(): spec required & validated ───────────────────────────────

    def test_requires_spec(self):
        q = self._build(table_spec=None)
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('table_spec', ctx.exception.error_dict)

    def test_rejects_non_numeric_answer(self):
        q = self._build(table_spec={
            'headers': ['x', 'y'],
            'rows': [[{'given': '0'}, {'answer': 'left'}]],
        })
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('table_spec', ctx.exception.error_dict)

    def test_valid_spec_passes(self):
        self._build().full_clean()  # must not raise

    def test_rejects_answer_rows(self):
        q = self._build()
        q.save()
        Answer.objects.create(question=q, answer_text='-1', is_correct=True)
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('question_type', ctx.exception.error_dict)

    # ── table_data render helper ─────────────────────────────────────────

    def test_render_data_shape(self):
        d = self._build().table_data
        self.assertIsNotNone(d)
        self.assertEqual(d['headers'], ['x', 'y'])
        self.assertEqual(len(d['rows']), 3)
        # Column 0 is given (shown), column 1 is a blank the student fills.
        first = d['rows'][0]
        self.assertTrue(first[0]['given'])
        self.assertEqual(first[0]['value'], '-1')
        self.assertFalse(first[1]['given'])
        self.assertEqual(first[1]['rc'], '0,1')

    def test_render_data_none_for_other_types(self):
        q = Question(level=self.level, question_text='x', points=1,
                     question_type=Question.SHORT_ANSWER)
        self.assertIsNone(q.table_data)

    # ── plugin grading dispatch (homework take surface) ──────────────────

    def test_plugin_grades_correct_submission(self):
        q = self._build()
        q.save()
        result = MathsPlugin().grade_answer(q.pk, {
            f'answer_{q.id}': '{"cells": {"0,1": "-1", "1,1": "-2", "2,1": "2"}}',
        })
        self.assertTrue(result['is_correct'])
        self.assertEqual(result['points_earned'], q.points)

    def test_plugin_grades_wrong_submission(self):
        # Two cells of three right: the table is not correct, but the two cells
        # the student did get still earn their share of the points.
        q = self._build()
        q.save()
        result = MathsPlugin().grade_answer(q.pk, {
            f'answer_{q.id}': '{"cells": {"0,1": "-1", "1,1": "-2", "2,1": "99"}}',
        })
        self.assertFalse(result['is_correct'])
        self.assertEqual(result['points_earned'], round(q.points * 2 / 3, 2))
        self.assertEqual(result['answer_data']['parts_correct'], 2)
        self.assertEqual(result['answer_data']['parts_total'], 3)

    def test_plugin_scores_zero_when_every_cell_is_wrong(self):
        q = self._build()
        q.save()
        result = MathsPlugin().grade_answer(q.pk, {
            f'answer_{q.id}': '{"cells": {"0,1": "97", "1,1": "98", "2,1": "99"}}',
        })
        self.assertFalse(result['is_correct'])
        self.assertEqual(result['points_earned'], 0)
