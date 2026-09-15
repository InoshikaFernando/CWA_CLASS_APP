"""A money answer is not wrong because of its formatting.

A typed answer is compared as a STRING on the ``text`` path, so a question
whose key is stored ``$1.25`` marked a child typing ``1.25`` WRONG, and a key
of ``2.5`` marked ``2.50`` wrong. Same number, no different answer — and money
keys carry the ``$`` more often than not, which is what makes it bite.

``maths.answer_values`` already knew how to read "what number is this answer
text?", including the currency symbol and a trailing unit, but only the AUDIT
tooling ever called it; the grader compared strings. Same shape as CPP-407's
dash bug: the helper that could see the equality existed, and the thing doing
the marking did not use it.

The two guards below are the whole design, and each has a real question behind
it. Forgiving formatting must not forgive the thing being taught:

* a fraction is not a decimal — "write 5/4 as a decimal" is in the bank;
* the key's precision is a FLOOR — "Ten cents is $0.10 and one dollar is
  $1.00" teaches two-place money form, so ``1`` must stay wrong for ``1.00``.
  That case is pinned by worksheets/tests/test_partial_credit_views.py, which
  is what caught an earlier, laxer version of this fix.
"""
from django.test import TestCase

from maths.algebra_grading import decimal_quantity_match, match_value


class FormattingIsForgivenTests(TestCase):
    """Spellings of one number that are not a different answer."""

    def test_the_currency_symbol_does_not_decide_the_mark(self):
        self.assertTrue(match_value('1.25', '$1.25'))
        self.assertTrue(match_value('$1.25', '1.25'))

    def test_a_student_may_write_more_decimal_places_than_the_key(self):
        self.assertTrue(match_value('2.50', '2.5'))
        self.assertTrue(match_value('1.250', '1.25'))

    def test_both_together(self):
        self.assertTrue(match_value('$2.50', '2.5'))

    def test_a_bare_number_answers_a_key_that_states_the_unit(self):
        # The unit is implied by the question; quantities_match treats a blank
        # unit as compatible with a stated one.
        self.assertTrue(match_value('5', '5 cm'))


class TheObjectiveIsNotForgivenTests(TestCase):
    """The guards. Each of these must stay WRONG."""

    def test_fewer_decimal_places_than_the_key_is_wrong(self):
        # "one dollar is $1.00" — the trailing zeros are the point.
        self.assertFalse(match_value('1', '1.00'))
        self.assertFalse(match_value('2.5', '2.50'))

    def test_a_fraction_is_not_a_decimal(self):
        # "Write 5/4 as a decimal" would otherwise mark a student correct for
        # doing none of the conversion asked for.
        self.assertFalse(match_value('5/4', '1.25'))
        self.assertFalse(match_value('1.25', '5/4'))
        self.assertFalse(match_value('1 1/4', '1.25'))

    def test_the_same_number_in_a_different_unit_is_wrong(self):
        self.assertFalse(match_value('4 g', '4 kg'))
        self.assertFalse(match_value('4 kg', '4 g'))

    def test_a_leading_minus_still_decides_the_mark(self):
        self.assertFalse(match_value('-5', '5'))
        self.assertFalse(match_value('5', '-5'))

    def test_a_different_number_is_still_wrong(self):
        self.assertFalse(match_value('1.26', '1.25'))
        self.assertFalse(match_value('12.5', '1.25'))

    def test_a_percentage_is_not_its_decimal(self):
        # 125% and 1.25 are the same ratio but not interchangeable answers;
        # parse_answer_value refuses "125%", so this never engages.
        self.assertFalse(match_value('125%', '1.25'))
        self.assertFalse(match_value('1.25', '125%'))


class NotANumberTests(TestCase):
    """Ordinary answers must not be dragged through the numeric comparison."""

    def test_words_are_not_numbers(self):
        self.assertFalse(decimal_quantity_match('felt', 'left'))

    def test_an_empty_answer_is_never_correct(self):
        self.assertFalse(decimal_quantity_match('', '1.25'))
        self.assertFalse(decimal_quantity_match('1.25', ''))

    def test_a_compound_answer_is_not_a_single_value(self):
        # parse_answer_value returns None for these, and None is "cannot
        # compare" rather than "equal".
        self.assertFalse(decimal_quantity_match('6 and 2', '8'))
        self.assertFalse(decimal_quantity_match('x = 4, y = 2', '4'))

    def test_identical_text_still_matches_as_it_always_did(self):
        self.assertTrue(match_value('1.25', '1.25'))
