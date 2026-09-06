"""Typographic dashes are the same sign as a hyphen (CPP-407).

CPP-406's question stores its answer key as ``–3`` — an EN DASH, not a
hyphen-minus. Nothing compared the two as the same character, so:

* a child typing ``-3`` on a typed-answer question was **marked wrong for a
  correct answer**, and nobody reported it because it looks like the student
  getting it wrong rather than like a bug;
* ``parse_answer_value('–3')`` returned None, so the audit reported those
  questions as UNVERIFIED instead of checking them — the one tool that could
  have found this could not read the rows it applies to.

The guard that matters most is at the bottom: folding dashes must NOT make a
leading minus meaningless. ``-5`` still has to be wrong for a question whose
answer is ``5``.
"""
from fractions import Fraction

from django.test import TestCase

from maths.algebra_grading import fold_answer, fold_dashes, match_value
from maths.answer_values import parse_answer_value
from maths.answer_verification import evaluate_expression, extract_expression

# HYPHEN, NON-BREAKING HYPHEN, FIGURE DASH, EN DASH, EM DASH, HORIZONTAL BAR,
# MINUS SIGN — every dash a worksheet or a PDF importer can produce.
DASHES = ['‐', '‑', '‒', '–', '—', '―', '−']


class FoldDashesTests(TestCase):

    def test_every_dash_variant_becomes_a_hyphen(self):
        for dash in DASHES:
            with self.subTest(hex(ord(dash))):
                self.assertEqual(fold_dashes(f'{dash}3'), '-3')

    def test_an_ascii_hyphen_is_untouched(self):
        self.assertEqual(fold_dashes('-3'), '-3')

    def test_text_without_a_dash_is_untouched(self):
        self.assertEqual(fold_dashes('3 apples'), '3 apples')


class TypedAnswerGradingTests(TestCase):
    """The defect as a child meets it."""

    def test_the_reported_case_is_now_correct(self):
        # Stored key '–3' (EN DASH); the student types an ordinary hyphen.
        self.assertTrue(match_value('-3', '–3'))

    def test_it_works_in_both_directions(self):
        self.assertTrue(match_value('–3', '-3'))
        self.assertTrue(match_value('–3', '−3'))

    def test_every_dash_variant_grades_correct(self):
        for dash in DASHES:
            with self.subTest(hex(ord(dash))):
                self.assertTrue(match_value('-7', f'{dash}7'))
                self.assertTrue(match_value(f'{dash}7', '-7'))

    def test_algebra_format_too(self):
        self.assertTrue(match_value('-3', '–3', 'algebra'))
        self.assertTrue(match_value('2x - 5', '2x – 5', 'algebra'))

    def test_a_wrong_answer_is_still_wrong(self):
        self.assertFalse(match_value('-3', '–4'))
        self.assertFalse(match_value('3', '–3'))

    # ---- the guard ------------------------------------------------------
    def test_a_leading_minus_stays_significant(self):
        """Folding dashes must not make the sign meaningless.

        ``fold_answer`` folds hyphens BETWEEN LETTERS to a space so
        "fifty-three" == "fifty three". A leading minus on a number is a
        different thing entirely and has to survive, or every negative answer
        starts matching its positive.
        """
        self.assertFalse(match_value('-5', '5'))
        self.assertFalse(match_value('–5', '5'))
        self.assertFalse(match_value('5', '–5'))
        self.assertNotEqual(fold_answer('-5'), fold_answer('5'))

    def test_worded_answers_still_fold_across_a_dash(self):
        # An en dash between letters behaves like the hyphen it stands in for.
        self.assertTrue(match_value('fifty three', 'fifty–three'))
        self.assertTrue(match_value('fifty-three', 'fifty–three'))


class AuditReadabilityTests(TestCase):
    """The checker has to be able to read what it is checking."""

    def test_parse_answer_value_reads_a_typographic_minus(self):
        for dash in DASHES:
            with self.subTest(hex(ord(dash))):
                self.assertEqual(parse_answer_value(f'{dash}3'), Fraction(-3))

    def test_a_mixed_number_keeps_its_sign(self):
        self.assertEqual(parse_answer_value('–2 1/2'), Fraction(-5, 2))

    def test_a_non_number_is_still_none(self):
        self.assertIsNone(parse_answer_value('three'))
        self.assertIsNone(parse_answer_value('6/30 and 2/30'))

    def test_an_expression_written_with_an_en_dash_evaluates(self):
        expression = extract_expression('What is 12 – 5?')
        self.assertEqual(expression.strip(), '12 - 5')
        self.assertEqual(evaluate_expression(expression), Fraction(7))
