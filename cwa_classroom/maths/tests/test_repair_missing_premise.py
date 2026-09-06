"""The missing-premise repair (CPP-406).

A Year 7 student met, in full, ``The value of x is:`` with options -3 / 3 / -7
/ 7 and no equation. These tests pin the two properties that matter:

* the command NEVER writes a question whose equation and answer key disagree —
  a quietly wrong question is worse than an obviously broken one;
* it refuses the stems whose missing premise is a figure or a table, where an
  equation would be the wrong repair entirely.
"""
from fractions import Fraction

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from classroom.models import Level
from maths.management.commands.repair_missing_premise import (
    as_number, generate_equation, missing_premise, render_linear,
    solve_linear, stem_is_bare,
)
from maths.models import Answer, Question


class DashToleranceTests(TestCase):
    """Imported content is full of typographic dashes."""

    def test_an_en_dash_minus_reads_as_a_negative_number(self):
        # The reported question's answer key is '–3' (EN DASH). Fraction() and
        # answer_values.parse_answer_value both read that as "not a number".
        self.assertEqual(as_number('–3'), Fraction(-3))
        self.assertEqual(as_number('−3'), Fraction(-3))    # MINUS SIGN
        self.assertEqual(as_number('-3'), Fraction(-3))    # plain hyphen

    def test_a_non_number_is_none_not_zero(self):
        self.assertIsNone(as_number('three'))
        self.assertIsNone(as_number(''))


class LinearEquationTests(TestCase):

    def test_solves_the_shapes_it_claims_to(self):
        for equation, expected in [('x + 7 = 4', -3), ('2x + 7 = 1', -3),
                                   ('3x = -9', -3), ('x - 3 = 0', 3),
                                   ('-x + 1 = 4', -3)]:
            with self.subTest(equation):
                self.assertEqual(solve_linear(equation, 'x'), expected)

    def test_refuses_what_it_cannot_read_rather_than_guessing(self):
        for equation in ['2(x + 1) = 8', 'x + y = 4', 'x² = 9', 'nonsense']:
            with self.subTest(equation):
                self.assertIsNone(solve_linear(equation, 'x'))

    def test_a_different_unknown_is_not_silently_accepted(self):
        self.assertIsNone(solve_linear('y + 7 = 4', 'x'))

    def test_rendering_round_trips(self):
        for a, b, c in [(1, 7, 4), (2, 7, 1), (3, 0, -9), (-1, 1, 4)]:
            with self.subTest((a, b, c)):
                self.assertEqual(
                    solve_linear(render_linear('x', a, b, c), 'x'),
                    Fraction(c - b, a))


class DetectionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=968, defaults={'display_name': 'premise fixture'})

    def _q(self, text, image=''):
        return Question.objects.create(
            level=self.level, question_text=text, image=image,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)

    def test_the_reported_stem_is_flagged(self):
        self.assertTrue(missing_premise(self._q('The value of x is:')))

    def test_a_stem_that_carries_its_equation_is_not(self):
        self.assertFalse(missing_premise(self._q('3x + 7 = 22. The value of x is:')))

    def test_a_stem_with_an_image_is_not(self):
        q = self._q('Find the value of x.',
                    image='questions/year8/angles/lines.png')
        self.assertFalse(missing_premise(q))

    def test_ordinary_algebra_questions_are_left_alone(self):
        for text in ['Expand: (2 - a)(2 + a)', 'Solve the inequality: 5x + 2 < 47',
                     'State the solution to the equation: 5y = 45',
                     'Find: (x + 8)²', 'Expand ab(8 - a).']:
            with self.subTest(text):
                self.assertFalse(missing_premise(self._q(text)))

    def test_a_stem_describing_a_figure_is_not_bare(self):
        """An equation cannot stand in for a diagram or a table."""
        for text in ['Two straight lines intersect. Find the value of x.',
                     'The table represents a probability distribution. '
                     'Solve for k.']:
            with self.subTest(text):
                q = self._q(text)
                self.assertTrue(missing_premise(q))     # still a real fault
                self.assertFalse(stem_is_bare(q))       # but not this one's


class RepairCommandTests(TestCase):
    """End to end, on a replica of the reported question."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=969, defaults={'display_name': 'repair fixture'})

    def _reported(self):
        q = Question.objects.create(
            level=self.level, question_text='The value of x is:',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        for order, (text, correct) in enumerate(
                [('–3', True), ('3', False), ('–7', False), ('7', False)]):
            Answer.objects.create(question=q, answer_text=text,
                                  is_correct=correct, order=order)
        return q

    def test_the_generated_equation_borrows_a_distractor(self):
        """So the wrong options stay plausible slips.

        Options are -3 (correct), 3, -7, 7. Taking 7 as the constant rebuilds
        x + 7 = 4: 3 is the sign slip, ±7 the constant grabbed off the page. An
        arbitrary coefficient would leave three options matching no mistake.
        """
        q = self._reported()
        a, b, c = generate_equation(q, 'x', Fraction(-3))
        self.assertEqual(render_linear('x', a, b, c), 'x + 7 = 4')

    def test_dry_run_writes_nothing(self):
        q = self._reported()
        call_command('repair_missing_premise', '--question', q.id, '--generate')
        q.refresh_from_db()
        self.assertEqual(q.question_text, 'The value of x is:')

    def test_apply_prepends_the_equation(self):
        q = self._reported()
        call_command('repair_missing_premise', '--question', q.id,
                     '--generate', '--apply')
        q.refresh_from_db()
        self.assertTrue(q.question_text.startswith('x + 7 = 4'))
        self.assertIn('The value of x is:', q.question_text)

    def test_a_second_run_is_a_no_op(self):
        q = self._reported()
        call_command('repair_missing_premise', '--question', q.id,
                     '--generate', '--apply')
        q.refresh_from_db()
        repaired = q.question_text
        with self.assertRaises(CommandError):
            call_command('repair_missing_premise', '--question', q.id,
                         '--generate', '--apply')
        q.refresh_from_db()
        self.assertEqual(q.question_text, repaired)

    def test_a_supplied_equation_that_disagrees_is_refused(self):
        """The guard the whole command exists for."""
        q = self._reported()
        with self.assertRaises(CommandError) as ctx:
            call_command('repair_missing_premise', '--question', q.id,
                         '--equation', 'x + 7 = 5', '--apply')
        self.assertIn('disagree', str(ctx.exception))
        q.refresh_from_db()
        self.assertEqual(q.question_text, 'The value of x is:')

    def test_a_supplied_equation_that_agrees_is_written(self):
        q = self._reported()
        call_command('repair_missing_premise', '--question', q.id,
                     '--equation', '2x + 7 = 1', '--apply')
        q.refresh_from_db()
        self.assertTrue(q.question_text.startswith('2x + 7 = 1'))

    def test_generate_refuses_a_stem_that_describes_a_figure(self):
        q = Question.objects.create(
            level=self.level, difficulty=1, points=1,
            question_text='Two straight lines intersect. Find the value of x.',
            question_type=Question.MULTIPLE_CHOICE)
        Answer.objects.create(question=q, answer_text='40', is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text='50', is_correct=False, order=1)

        with self.assertRaises(CommandError) as ctx:
            call_command('repair_missing_premise', '--question', q.id,
                         '--generate', '--apply')
        self.assertIn('diagram', str(ctx.exception))
        q.refresh_from_db()
        self.assertTrue(q.question_text.startswith('Two straight lines'))

    def test_several_correct_options_are_refused(self):
        q = self._reported()
        q.answers.filter(answer_text='3').update(is_correct=True)
        with self.assertRaises(CommandError) as ctx:
            call_command('repair_missing_premise', '--question', q.id,
                         '--generate', '--apply')
        self.assertIn('flagged correct', str(ctx.exception))

    def test_a_question_with_no_missing_premise_is_refused(self):
        q = Question.objects.create(
            level=self.level, question_text='3x + 7 = 22. The value of x is:',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        Answer.objects.create(question=q, answer_text='5', is_correct=True, order=0)
        with self.assertRaises(CommandError):
            call_command('repair_missing_premise', '--question', q.id,
                         '--generate', '--apply')
