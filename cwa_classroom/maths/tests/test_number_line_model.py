"""Model tests for the ``number_line`` question type.

The type constant/choice, the ``Question.clean()`` branch that requires a valid
``number_line_spec`` and forbids answer options, and the ``number_line_data``
render helper (backdrop SVG + tappable tick positions / read-mode arrows).
Mirrors ``test_measure_model`` / ``test_draw_on_grid_model``.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question


class NumberLineModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993, defaults={'display_name': 'number_line fixture'})

    def _build(self, **overrides):
        fields = dict(
            level=self.level,
            question_text='Mark 2 on the number line.',
            question_type=Question.NUMBER_LINE,
            difficulty=1,
            points=1,
            number_line_spec={'min': -3, 'max': 7, 'step': 1,
                              'mode': 'mark', 'target': [2]},
        )
        fields.update(overrides)
        return Question(**fields)

    # ── type registration ────────────────────────────────────────────────

    def test_type_constant_and_choice(self):
        self.assertEqual(Question.NUMBER_LINE, 'number_line')
        self.assertIn(
            ('number_line', 'Number Line (mark or read a value)'),
            Question.QUESTION_TYPES,
        )

    # ── clean(): spec required & validated ───────────────────────────────

    def test_requires_spec(self):
        q = self._build(number_line_spec=None)
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('number_line_spec', ctx.exception.error_dict)

    def test_rejects_off_tick_target(self):
        q = self._build(number_line_spec={
            'min': 0, 'max': 10, 'step': 2, 'mode': 'mark', 'target': [3]})
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('number_line_spec', ctx.exception.error_dict)

    def test_valid_spec_passes(self):
        self._build().full_clean()  # must not raise

    def test_rejects_answer_rows(self):
        q = self._build()
        q.save()
        Answer.objects.create(question=q, answer_text='2', is_correct=True)
        with self.assertRaises(ValidationError) as ctx:
            q.clean()
        self.assertIn('question_type', ctx.exception.error_dict)

    # ── number_line_data render helper ───────────────────────────────────

    def test_render_data_mark_mode(self):
        q = self._build()
        d = q.number_line_data
        self.assertIsNotNone(d)
        self.assertEqual(d['mode'], 'mark')
        # 11 ticks (-3..7) → 11 tappable dots, each carrying its value.
        self.assertEqual(len(d['dots']), 11)
        self.assertEqual({dot['value'] for dot in d['dots']},
                         set(range(-3, 8)))
        self.assertEqual(d['target_values'], [2])
        self.assertIn('<line', d['svg'])  # backdrop markup (axis/ticks) produced

    def test_render_data_read_mode_has_no_dots(self):
        q = self._build(
            question_text='What does the arrow point to?',
            number_line_spec={'min': 0, 'max': 10, 'step': 2,
                              'mode': 'read', 'given': [6]})
        d = q.number_line_data
        self.assertEqual(d['mode'], 'read')
        self.assertEqual(d['dots'], [])            # read mode is typed, not tapped
        self.assertEqual([g['value'] for g in d['given']], [6])
        self.assertEqual(d['target_values'], [6])  # target defaults to given

    def test_render_data_none_for_other_types(self):
        q = Question(level=self.level, question_text='x', points=1,
                     question_type=Question.SHORT_ANSWER)
        self.assertIsNone(q.number_line_data)
