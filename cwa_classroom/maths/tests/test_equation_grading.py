"""Pure-function tests for equation-equivalence grading (answer_format='equation').

Covers ``is_equation_answer_correct`` — "write the equation of this parabola"
questions where the key is vertex form but any algebraically equivalent spelling
(vertex / factored / expanded) is accepted. No DB. Cases are drawn from the
Foundations-of-Math quadratics booklet answer keys.
"""
from django.test import SimpleTestCase, TestCase

from classroom.models import Level
from maths.algebra_grading import is_equation_answer_correct
from maths.models import Answer, Question


class EquationEquivalenceTests(SimpleTestCase):
    def test_identical_vertex_form(self):
        self.assertTrue(is_equation_answer_correct(
            'y = 2(x-1)^2 - 2', 'y = 2(x-1)^2 - 2'))

    def test_expanded_equals_vertex(self):
        # 2(x-1)^2 - 2 = 2x^2 - 4x
        self.assertTrue(is_equation_answer_correct(
            'y = 2x^2 - 4x', 'y = 2(x-1)^2 - 2'))

    def test_unicode_superscript_and_spacing(self):
        self.assertTrue(is_equation_answer_correct(
            'y=2(x-1)²-2', 'y = 2(x-1)^2 - 2'))

    def test_negative_leading_coefficient(self):
        # Booklet answer 1: y = -(x-2)^2
        self.assertTrue(is_equation_answer_correct(
            'y = -(x-2)^2', 'y = -(x - 2)^2'))
        self.assertTrue(is_equation_answer_correct(
            'y = -x^2 + 4x - 4', 'y = -(x-2)^2'))

    def test_fractional_coefficient(self):
        # Booklet answer 4: y = -3/2 x^2 + 6
        self.assertTrue(is_equation_answer_correct(
            'y = -3/2x^2 + 6', 'y = -3/2 x^2 + 6'))
        # …and its factored form -3/2(x^2 - 4) = -3/2 x^2 + 6
        self.assertTrue(is_equation_answer_correct(
            'y = -3/2(x^2 - 4)', 'y = -3/2 x^2 + 6'))

    def test_half_vertex_form(self):
        # Booklet answer 5: y = 1/2(x+2)^2 + 1  →  0.5x^2 + 2x + 3
        self.assertTrue(is_equation_answer_correct(
            'y = 0.5x^2 + 2x + 3', 'y = 1/2(x+2)^2 + 1'))

    def test_factored_form_accepted(self):
        # y = (x-1)(x-3) = x^2 - 4x + 3 = (x-2)^2 - 1
        self.assertTrue(is_equation_answer_correct(
            'y = (x-1)(x-3)', 'y = (x-2)^2 - 1'))

    def test_rearranged_equation_isolates_y(self):
        # Example #3: y + 4 = 2(x-2)^2  ≡  y = 2(x-2)^2 - 4
        self.assertTrue(is_equation_answer_correct(
            'y + 4 = 2(x-2)^2', 'y = 2(x-2)^2 - 4'))

    def test_bare_expression_accepted(self):
        # Student omits "y ="
        self.assertTrue(is_equation_answer_correct(
            '2(x-1)^2 - 2', 'y = 2(x-1)^2 - 2'))

    def test_fx_notation_accepted(self):
        self.assertTrue(is_equation_answer_correct(
            'f(x) = 2x^2 - 4x', 'y = 2(x-1)^2 - 2'))

    def test_alternative_forms_pipe(self):
        self.assertTrue(is_equation_answer_correct(
            'y = x^2 - 4x + 4', 'y = (x-2)^2 | y = x^2 - 4x + 4'))

    # ── wrong answers ────────────────────────────────────────────────────

    def test_wrong_constant_is_incorrect(self):
        self.assertFalse(is_equation_answer_correct(
            'y = 2(x-1)^2 + 1', 'y = 2(x-1)^2 - 2'))

    def test_wrong_stretch_is_incorrect(self):
        self.assertFalse(is_equation_answer_correct(
            'y = 3(x-1)^2 - 2', 'y = 2(x-1)^2 - 2'))

    def test_wrong_vertex_shift_is_incorrect(self):
        self.assertFalse(is_equation_answer_correct(
            'y = 2(x+1)^2 - 2', 'y = 2(x-1)^2 - 2'))

    def test_missing_answer_is_incorrect(self):
        self.assertFalse(is_equation_answer_correct('', 'y = 2(x-1)^2 - 2'))

    def test_garbage_is_incorrect(self):
        self.assertFalse(is_equation_answer_correct('banana', 'y = 2(x-1)^2 - 2'))
        self.assertFalse(is_equation_answer_correct('y = 2(x-1^2 - 2', 'y = 2(x-1)^2 - 2'))

    def test_nonlinear_in_y_is_incorrect(self):
        # y^2 = ... is not a function y = f(x); grade wrong, never raise.
        self.assertFalse(is_equation_answer_correct(
            'y^2 = x', 'y = 2(x-1)^2 - 2'))


class EquationAnswerFormatRoutingTests(TestCase):
    """The 'equation' answer_format routes Question.grade_text_answer to the
    equivalence grader (not exact match)."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=989, defaults={'display_name': 'equation fixture'})

    def _question(self):
        q = Question.objects.create(
            level=self.level,
            question_text='Write the equation for this parabola.',
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_EQUATION,
            points=1,
        )
        Answer.objects.create(question=q, answer_text='y = 2(x-1)^2 - 2', is_correct=True)
        return q

    def test_equivalent_form_grades_correct(self):
        q = self._question()
        self.assertTrue(q.grade_text_answer('y = 2x^2 - 4x'))  # expanded form

    def test_different_curve_grades_wrong(self):
        q = self._question()
        self.assertFalse(q.grade_text_answer('y = 2(x-1)^2 + 5'))

    def test_format_choice_registered(self):
        self.assertEqual(Question.ANSWER_FORMAT_EQUATION, 'equation')
        self.assertIn(
            ('equation', 'Equation — algebraic equivalence (accepts vertex / factored / expanded form)'),
            Question.ANSWER_FORMAT_CHOICES,
        )
