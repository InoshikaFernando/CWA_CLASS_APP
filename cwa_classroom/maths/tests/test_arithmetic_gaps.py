"""Solving the arithmetic a question prints — maths.arithmetic_gaps.

The defect these pin: a conversion run over the question bank refused 35
questions whose gaps it could not fill, all of them shapes where the question
already prints the sum::

    "Write the sum and then write the product:
     4 + 4 + 4 + 4 + 4 + 4 = ______ and 4 x 6 = ______"     stored answer: 24

Two gaps, one stored answer. The row rules cannot say which gap the 24 belongs
to — and the true answer is that BOTH of them are 24, which no reading of one
row could have produced. The arithmetic is printed, so it is solved; the stored
answer is kept for what it can prove, that the question was read the way its
author meant it.

Every case below is a question that exists in the bank.
"""
from fractions import Fraction

from django.test import SimpleTestCase

from maths.arithmetic_gaps import read_arithmetic_gaps


def _solved(text):
    """The gap values in gap order, as a child would write them."""
    found = read_arithmetic_gaps(text)
    return [str(found[index]) for index in sorted(found)]


class SumAndProductTests(SimpleTestCase):
    """"Write the sum and then write the product" — 19 questions, both gaps
    the same value, and the stored answer only ever filled one."""

    def test_the_sum_and_the_product_are_both_solved(self):
        self.assertEqual(
            _solved('Write the sum and then write the product: '
                    '4 + 4 + 4 + 4 + 4 + 4 = ______ and 4 x 6 = ______'),
            ['24', '24'])

    def test_a_seven_times_table_fact(self):
        self.assertEqual(
            _solved('Write the sum and then write the product: '
                    '7 + 7 + 7 + 7 + 7 + 7 + 7 = ______ and 7 x 7 = ______'),
            ['49', '49'])

    def test_the_smallest_one_in_the_bank(self):
        self.assertEqual(
            _solved('Write the sum and then write the product: '
                    '1 + 1 = ______ and 1 x 2 = ______'),
            ['2', '2'])


class CountAndTotalTests(SimpleTestCase):
    """"8 + 8 + 8 = ____ x 8" — the gap is a FACTOR, not the answer.

    Five questions whose first gap is the number of addends. Nothing in the
    stored answer (24) says 3; the equation does.
    """

    def test_the_missing_factor_comes_out_of_the_equation(self):
        self.assertEqual(
            _solved('8 + 8 + 8 = ____ x 8, and 8 + 8 + 8 = ____ . '
                    'What is 3 x 8?'),
            ['3', '24'])

    def test_a_longer_one_of_the_same_family(self):
        self.assertEqual(
            _solved('8 + 8 + 8 + 8 + 8 + 8 + 8 = ____ x 8, and '
                    '8 + 8 + 8 + 8 + 8 + 8 + 8 = ____ . What is 7 x 8?'),
            ['7', '56'])

    def test_the_trailing_question_is_not_an_equation(self):
        # "What is 3 x 8?" has no "=", so it is prose, not a statement with a
        # gap this must account for.
        self.assertEqual(len(read_arithmetic_gaps(
            '8 + 8 = ____ x 8, and 8 + 8 = ____ . What is 2 x 8?')), 2)


class EqualAddendsTests(SimpleTestCase):
    """"7 x 4 = 4 + 4 + _ + _ + _ + _ + _ = _" — five gaps in one sum.

    Arithmetic alone cannot split a total across five unknowns. What settles
    it is that every printed addend is the same number, and that filling the
    gaps with it comes to exactly what the other side of the equation says.
    """

    def test_the_repeated_addend_fills_every_gap(self):
        self.assertEqual(
            _solved('7 x 4 = 4 + 4 + ___ + ___ + ___ + ___ + ___ = ___. '
                    'What is the total?'),
            ['4', '4', '4', '4', '4', '28'])

    def test_the_shorter_one_of_the_pair(self):
        self.assertEqual(
            _solved('6 x 4 = 4 + 4 + ___ + ___ + ___ + ___ = ___. '
                    'What is the total?'),
            ['4', '4', '4', '4', '24'])

    def test_addends_that_are_not_all_the_same_are_refused(self):
        # 3 + 5 + _ + _ = 20 is 6 and 6, or 4 and 8, or anything else.
        self.assertEqual(read_arithmetic_gaps('Fill in: 3 + 5 + ___ + ___ = 20'),
                         {})

    def test_gaps_that_do_not_come_to_the_total_are_refused(self):
        # Every printed addend is 4, but 4 x 5 is 20, not 21 — so either the
        # question or its total is wrong, and neither is safe to fill.
        self.assertEqual(
            read_arithmetic_gaps('4 + 4 + ___ + ___ + ___ = 21'), {})


class WhatItRefusesTests(SimpleTestCase):
    """The questions in the same batch this must keep its hands off."""

    def test_a_gap_inside_a_number_is_not_a_term(self):
        # The seven percentage questions: the third gap is the digits AFTER
        # the point, and reading "0" as a known side would fill every gap
        # with zero.
        self.assertEqual(read_arithmetic_gaps(
            'Write 90% as a fraction over 100, as a fraction, and as a '
            'decimal (fill in: __/100 = __ = 0.__).'), {})

    def test_a_gap_ending_a_sentence_is_not_a_decimal(self):
        # The other side of that rule: "= ___." is a full stop, and treating
        # it as a decimal point refused this whole family.
        self.assertEqual(
            _solved('6 x 4 = 4 + 4 + ___ + ___ + ___ + ___ = ___.'),
            ['4', '4', '4', '4', '24'])

    def test_letters_in_the_arithmetic_are_refused(self):
        # The six "complete the factorisation" questions.
        self.assertEqual(read_arithmetic_gaps(
            'Complete the factorisation: ____ − 18xyz = ____(x − 3z).'), {})

    def test_a_number_pattern_is_not_arithmetic_it_can_read(self):
        self.assertEqual(read_arithmetic_gaps(
            'Complete the pattern: 30, ___, 60, 75, ___, ___.'), {})

    def test_a_sentence_with_no_arithmetic_at_all(self):
        self.assertEqual(read_arithmetic_gaps(
            'A triangle has ___ sides and ___ angles.'), {})

    def test_a_gap_outside_every_statement_refuses_the_question(self):
        # Whole or not at all: the second gap belongs to no equation, so the
        # first is not filled either.
        self.assertEqual(read_arithmetic_gaps(
            '2 + 2 = ___, and the shape has ___ sides.'), {})

    def test_two_sides_that_disagree_are_refused(self):
        self.assertEqual(read_arithmetic_gaps('2 + 2 = 5 = ___'), {})

    def test_mixed_operators_in_one_side_are_refused(self):
        self.assertEqual(read_arithmetic_gaps('2 + 3 x 4 = ___'), {})

    def test_a_thousands_separator_is_never_split(self):
        self.assertEqual(read_arithmetic_gaps('1,000 + 1,000 = ___'), {})

    def test_a_statement_with_no_known_side_settles_nothing(self):
        self.assertEqual(read_arithmetic_gaps('___ + ___ = ___'), {})

    def test_nothing_at_all(self):
        self.assertEqual(read_arithmetic_gaps(''), {})
        self.assertEqual(read_arithmetic_gaps(None), {})


class NonIntegerTests(SimpleTestCase):
    """A value that is not a whole number is still a value."""

    def test_a_missing_factor_may_be_a_fraction(self):
        self.assertEqual(read_arithmetic_gaps('___ x 4 = 10'),
                         {0: Fraction(5, 2)})
        self.assertEqual(_solved('___ x 4 = 10'), ['5/2'])

    def test_nothing_is_ever_divided_by_zero(self):
        self.assertEqual(read_arithmetic_gaps('___ x 0 = 10'), {})
