"""Factor order does not matter in a factorised answer (CPP-360).

"Factorise ``16p^2 - 81q^2``" stores its key as ``(4p - 9q)(4p + 9q)``.
Multiplication commutes, so a student writing ``(4p + 9q)(4p - 9q)`` has
factorised it correctly — and was marked wrong.

Two separate faults produced that, which is why both paths are covered here:

* the **text** path compared folded strings, so the swapped pair was simply
  unequal;
* the **algebra** path rejected any bracketed *student* answer up front to
  enforce the "expand the brackets" objective. On a factorised key that
  rejected the stored answer itself — the question could not be answered
  correctly by anyone, including by typing the key back verbatim. That is the
  ``test_the_stored_answer_matches_itself`` case below, and it failed before
  this fix.

The guards at the bottom are the point of the design: only ORDER is forgiven.
An expanded key still demands an expanded answer, so the "expand the brackets"
learning objective is untouched, and the expanded form of a *factorised* key
stays wrong because it is the question rather than the answer.
"""
from django.test import TestCase

from maths.algebra_grading import (
    is_reordered_product_correct,
    match_value,
)

# The two formats a factorise question is authored under. The bug reproduced
# under both, so every behavioural test runs against both.
FORMATS = ('text', 'algebra')

KEY = '(4p - 9q)(4p + 9q)'


class FactorOrderTests(TestCase):
    """The defect exactly as the reporter hit it, on both answer formats."""

    def test_swapped_factors_are_correct(self):
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertTrue(match_value('(4p + 9q)(4p - 9q)', KEY, fmt))

    def test_the_stored_answer_matches_itself(self):
        # Not a tautology: on answer_format='algebra' this returned False
        # before the fix, which made the question impossible to get right.
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertTrue(match_value(KEY, KEY, fmt))

    def test_spacing_and_term_order_inside_a_factor_do_not_matter(self):
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertTrue(match_value('(9q+4p)(4p-9q)', KEY, fmt))

    def test_three_factors_reorder_too(self):
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertTrue(
                    match_value('2(x - 1)(x + 1)', '2(x + 1)(x - 1)', fmt)
                )

    def test_a_repeated_factor_is_a_different_answer(self):
        # (4p - 9q)^2 is not (4p - 9q)(4p + 9q): same factors as a SET, but a
        # different multiset, and a genuinely different expression.
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertFalse(match_value('(4p - 9q)(4p - 9q)', KEY, fmt))

    def test_wrong_numbers_are_still_wrong(self):
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertFalse(match_value('(4p + 8q)(4p - 9q)', KEY, fmt))

    def test_the_overall_sign_is_not_forgiven(self):
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertFalse(
                    match_value('(x + 1)(x - 2)', '-(x + 1)(x - 2)', fmt)
                )


class LearningObjectiveGuardTests(TestCase):
    """Only order is forgiven — the objectives the grader enforces survive."""

    def test_an_expanded_answer_does_not_pass_a_factorised_key(self):
        # This is the question, not the answer: accepting it would mark a
        # student correct for doing no factorising at all.
        for fmt in FORMATS:
            with self.subTest(fmt):
                self.assertFalse(match_value('16p^2 - 81q^2', KEY, fmt))

    def test_brackets_still_fail_an_expanded_key(self):
        # The "expand the brackets" objective, unchanged: a factorised answer
        # to an expand question is still unfinished work.
        self.assertFalse(
            match_value('(2x + 3)(x - 5)', '2x^2 - 7x - 15', 'algebra')
        )

    def test_uncombined_like_terms_still_fail(self):
        self.assertFalse(
            match_value('2x^2 - 3x - 4x - 15', '2x^2 - 7x - 15', 'algebra')
        )

    def test_reordered_sums_still_pass(self):
        # CPP-359's case, which already worked — pinned so this change cannot
        # regress it.
        self.assertTrue(
            match_value('x^5 + 8x - x^2 + 12x^3', 'x^5 - x^2 + 12x^3 + 8x', 'text')
        )


class NotAProductTests(TestCase):
    """Ordinary answers must never be dragged into the algebra parser.

    The parser reads a run of letters as a product of single-letter variables,
    so an unguarded fallback would grade the words "felt" and "left" — same
    letters — as equal. Engaging only on a bracketed SUM is what prevents it.
    """

    def test_bracketed_words_are_not_factors(self):
        self.assertIsNone(_parsed('(cat)(dog)'))
        self.assertFalse(match_value('(cat)(dog)', '(dog)(cat)', 'text'))

    def test_a_plain_expression_is_not_a_product(self):
        self.assertIsNone(_parsed('16p^2-81q^2'))

    def test_a_single_factor_has_nothing_to_reorder(self):
        self.assertIsNone(_parsed('(x+1)'))

    def test_a_sum_of_brackets_is_not_a_product(self):
        # "(x+1)-(x-2)" is a difference; reordering it would change its value.
        self.assertIsNone(_parsed('(x+1)-(x-2)'))

    def test_unbalanced_brackets_are_rejected(self):
        self.assertIsNone(_parsed('(x+1)(x-2'))

    def test_an_empty_answer_is_never_correct(self):
        self.assertFalse(is_reordered_product_correct('', KEY))
        self.assertFalse(is_reordered_product_correct(KEY, ''))


def _parsed(text):
    """``_product_factors`` result, imported lazily to keep it private-ish."""
    from maths.algebra_grading import _product_factors
    return _product_factors(text)
