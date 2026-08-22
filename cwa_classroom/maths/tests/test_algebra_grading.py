"""
Tests for maths.algebra_grading — simplified-polynomial answer grading.

These are pure-Python unit tests (no DB), so they run fast and document the
exact grading contract: notation flexibility in, but the answer must be the
*fully simplified, expanded* polynomial.
"""
from fractions import Fraction

import pytest

from maths.algebra_grading import (
    MathAnswerError,
    _collect,
    _is_simple_expression,
    _parse_term,
    _split_terms,
    fold_degrees,
    fold_exponents,
    fold_inequalities,
    is_algebraic_answer_correct,
    is_reordered_expression_correct,
    normalize_notation,
)

EXPECTED = "2x^2 - 7x - 15"  # the canonical answer to (2x + 3)(x - 5)


# --------------------------------------------------------------------------- #
# The headline requirement: equal value but un-simplified form must be WRONG.
# --------------------------------------------------------------------------- #
class TestSimplificationRule:
    @pytest.mark.parametrize("answer", [
        "2x^2 - 7x - 15",      # exact
        "2x^2-7x-15",          # no spaces
        "  2x^2  -  7x - 15 ", # ragged spaces
        "-7x + 2x^2 - 15",     # reordered terms
        "-15 - 7x + 2x^2",     # fully reversed
    ])
    def test_accepts_simplified_equivalents(self, answer):
        assert is_algebraic_answer_correct(answer, EXPECTED) is True

    @pytest.mark.parametrize("answer", [
        "2x^2 - 3x - 4x - 15",   # like terms (the two x's) not combined
        "2x^2 - 7x - 15 + 0",    # trailing "+ 0" is an un-combined constant term
        "2x^2 - 7x - 10 - 5",    # constants not combined
        "x^2 + x^2 - 7x - 15",   # two x^2 terms not combined
        "2x^2 - 4x - 3x - 15",   # same idea, different split
    ])
    def test_rejects_uncombined_like_terms(self, answer):
        assert is_algebraic_answer_correct(answer, EXPECTED) is False

    @pytest.mark.parametrize("answer", [
        "(2x + 3)(x - 5)",   # not expanded at all
        "(2x+3)(x-5)",
        "2x(x) - 7x - 15",   # leftover bracket
    ])
    def test_rejects_unexpanded_brackets(self, answer):
        assert is_algebraic_answer_correct(answer, EXPECTED) is False


# --------------------------------------------------------------------------- #
# Wrong values are wrong (and a right form with a missing term is wrong).
# --------------------------------------------------------------------------- #
class TestWrongValues:
    @pytest.mark.parametrize("answer", [
        "2x^2 - 7x - 14",   # wrong constant
        "2x^2 + 7x - 15",   # wrong sign on middle term
        "2x^2 - 7x",        # missing constant term
        "2x^2 - 15",        # missing x term
        "x^2 - 7x - 15",    # wrong leading coefficient
        "",                 # empty
        "banana",           # nonsense
    ])
    def test_rejects(self, answer):
        assert is_algebraic_answer_correct(answer, EXPECTED) is False


# --------------------------------------------------------------------------- #
# Notation folding: superscripts, **, ×, spacing, case.
# --------------------------------------------------------------------------- #
class TestNotation:
    @pytest.mark.parametrize("answer", [
        "2x² - 7x - 15",     # unicode superscript
        "2x**2 - 7x - 15",   # python-style power
        "2X^2 - 7X - 15",    # uppercase variable
        "2·x^2 - 7·x - 15",  # middle-dot multiplication
        "2*x^2 - 7*x - 15",  # explicit star
    ])
    def test_accepts_notation_variants(self, answer):
        assert is_algebraic_answer_correct(answer, EXPECTED) is True

    def test_normalize_notation(self):
        assert normalize_notation("2X^2 - 7x - 15") == "2x^2-7x-15"
        assert normalize_notation("2x²") == "2x^2"
        assert normalize_notation("2x**2") == "2x^2"
        assert normalize_notation("x³ + x²") == "x^3+x^2"


# --------------------------------------------------------------------------- #
# Coefficients: fractions and decimals are exact and interchangeable.
# --------------------------------------------------------------------------- #
class TestCoefficients:
    def test_fraction_and_decimal_are_equal(self):
        assert is_algebraic_answer_correct("0.5x + 1", "1/2x + 1") is True
        assert is_algebraic_answer_correct("1/2x + 1", "0.5x + 1") is True

    def test_no_float_drift(self):
        # 0.1 + 0.2 style drift would break a naive float grader; Fraction is exact.
        assert is_algebraic_answer_correct("0.1x + 0.2x", "0.3x") is False  # uncombined
        assert is_algebraic_answer_correct("0.3x", "3/10x") is True

    def test_implicit_unit_coefficient(self):
        assert is_algebraic_answer_correct("x", "1x") is True
        assert is_algebraic_answer_correct("-x", "-1x") is True


# --------------------------------------------------------------------------- #
# Multi-variable polynomials (e.g. (x + y)(x - y) = x^2 - y^2).
# --------------------------------------------------------------------------- #
class TestMultiVariable:
    def test_difference_of_squares(self):
        expected = "x^2 - y^2"
        assert is_algebraic_answer_correct("x^2 - y^2", expected) is True
        assert is_algebraic_answer_correct("-y^2 + x^2", expected) is True
        assert is_algebraic_answer_correct("x^2 - xy + xy - y^2", expected) is False  # uncombined

    def test_mixed_product_term(self):
        # (x + y)^2 = x^2 + 2xy + y^2
        expected = "x^2 + 2xy + y^2"
        assert is_algebraic_answer_correct("x^2 + 2xy + y^2", expected) is True
        assert is_algebraic_answer_correct("x^2 + 2yx + y^2", expected) is True  # xy == yx
        assert is_algebraic_answer_correct("x^2 + xy + xy + y^2", expected) is False  # uncombined


# --------------------------------------------------------------------------- #
# Pipe-separated acceptable answers.
# --------------------------------------------------------------------------- #
class TestAlternatives:
    def test_pipe_alternatives(self):
        accepted = "2x^2 - 7x - 15|2x^2-7x-15"
        assert is_algebraic_answer_correct("-7x + 2x^2 - 15", accepted) is True

    def test_pipe_alternatives_distinct_polys(self):
        accepted = "x^2 - y^2|y^2 - x^2"  # either sign convention accepted
        assert is_algebraic_answer_correct("y^2 - x^2", accepted) is True
        assert is_algebraic_answer_correct("x^2 - y^2", accepted) is True


# --------------------------------------------------------------------------- #
# Lower-level building blocks.
# --------------------------------------------------------------------------- #
class TestInternals:
    def test_split_terms(self):
        assert _split_terms("2x^2-7x-15") == ["2x^2", "-7x", "-15"]
        assert _split_terms("-7x+2x^2-15") == ["-7x", "+2x^2", "-15"]

    def test_parse_term(self):
        assert _parse_term("2x^2") == (Fraction(2), (("x", 2),))
        assert _parse_term("-15") == (Fraction(-15), ())
        assert _parse_term("-x") == (Fraction(-1), (("x", 1),))
        assert _parse_term("3xy") == (Fraction(3), (("x", 1), ("y", 1)))

    def test_collect_strict_rejects_like_terms(self):
        with pytest.raises(MathAnswerError):
            _collect("x + x", strict=True)
        # ...but lenient collection just sums them (for teacher answers).
        assert _collect("x + x", strict=False) == {(("x", 1),): Fraction(2)}

    def test_collect_rejects_brackets(self):
        with pytest.raises(MathAnswerError):
            _collect("(x + 1)(x - 1)", strict=True)

    def test_zero_coefficients_dropped(self):
        assert _collect("x - x + 5", strict=False) == {(): Fraction(5)}


# --------------------------------------------------------------------------- #
# Empty / defensive inputs never raise out of the public function.
# --------------------------------------------------------------------------- #
class TestDefensive:
    @pytest.mark.parametrize("user,correct", [
        ("", "2x^2 - 7x - 15"),
        ("2x^2 - 7x - 15", ""),
        ("", ""),
        (None, "x"),
        ("x", None),
    ])
    def test_empty_inputs_return_false(self, user, correct):
        assert is_algebraic_answer_correct(user, correct) is False

    @pytest.mark.parametrize("answer", [
        "1/0",        # bare division by zero
        "1/0x + 2",   # zero-denominator coefficient on a term
        "x/0",        # (unparseable) — must not raise
        "1/0.0",      # decimal zero denominator
    ])
    def test_division_by_zero_is_wrong_not_a_crash(self, answer):
        # A student typing a zero-denominator fraction must be marked wrong,
        # never surface a ZeroDivisionError as an HTTP 500.
        assert is_algebraic_answer_correct(answer, "2x^2 - 7x - 15") is False


# --------------------------------------------------------------------------- #
# fold_exponents — exponent-insensitive matching for ordinary (non-algebra)
# maths answers, e.g. areas in cm². Powers the x² button on all typed answers.
# --------------------------------------------------------------------------- #
class TestFoldExponents:
    def test_all_power_notations_collapse_equal(self):
        forms = ["2cm^2", "2cm²", "2cm**2", "2cm2", "2 cm^2", "  2 CM 2 "]
        folded = {fold_exponents(f) for f in forms}
        assert folded == {"2cm2"}

    def test_plain_values_unaffected(self):
        assert fold_exponents("8") == "8"
        assert fold_exponents("1/2") == "1/2"
        assert fold_exponents("3.5") == "3.5"

    def test_cubed_and_higher(self):
        assert fold_exponents("cm³") == fold_exponents("cm^3") == "cm3"
        assert fold_exponents("x¹⁰") == fold_exponents("x^10") == "x10"


# --------------------------------------------------------------------------- #
# fold_inequalities — operator-spelling-insensitive matching so a stored
# inequality answer (x ≥ 2) matches however the student types the operator.
# --------------------------------------------------------------------------- #
class TestFoldInequalities:
    def test_all_ge_spellings_collapse_equal(self):
        forms = ["x ≥ 2", "x>=2", "x=>2"]
        folded = {fold_exponents(fold_inequalities(f)) for f in forms}
        assert folded == {"x>=2"}

    def test_all_le_spellings_collapse_equal(self):
        forms = ["x ≤ 5", "x<=5", "x=<5"]
        folded = {fold_exponents(fold_inequalities(f)) for f in forms}
        assert folded == {"x<=5"}

    def test_strict_and_nonstrict_stay_distinct(self):
        # x > 2 must NOT be accepted for a stored x ≥ 2.
        assert fold_inequalities("x>2") != fold_inequalities("x ≥ 2")
        assert fold_inequalities("x<2") != fold_inequalities("x ≤ 2")

    def test_not_equal_spellings_collapse_equal(self):
        # The keypad inserts ≠; ASCII <> and != must match it.
        forms = ["a ≠ b", "a<>b", "a!=b"]
        folded = {fold_exponents(fold_inequalities(f)) for f in forms}
        assert folded == {"a!=b"}

    def test_plain_values_unaffected(self):
        assert fold_inequalities("8") == "8"
        assert fold_inequalities("2x + 3") == "2x + 3"


# --------------------------------------------------------------------------- #
# fold_degrees — degree-insensitive matching so an angle answer grades the same
# with or without the ° the keypad button inserts (50 == 50°).
# --------------------------------------------------------------------------- #
class TestFoldDegrees:
    def test_with_and_without_degree_sign_collapse_equal(self):
        forms = ["50°", "50"]
        folded = {fold_exponents(fold_inequalities(fold_degrees(f))) for f in forms}
        assert folded == {"50"}

    def test_degree_sign_stripped(self):
        assert fold_degrees("50°") == "50"
        assert fold_degrees("90° ") == "90 "

    def test_plain_values_unaffected(self):
        assert fold_degrees("8") == "8"
        assert fold_degrees("2x + 3") == "2x + 3"


# --------------------------------------------------------------------------- #
# The term-order fallback used by plain-text ('text') answers.
# --------------------------------------------------------------------------- #
class TestReorderedExpression:
    """A written expression must grade the same whichever order its terms are in.

    "The cost is $110 room hire plus $12 per person — write an expression for
    p people" is an ordinary typed question, so it was graded by literal match
    and "110 + 12p" came back WRONG against the stored "12p + 110".
    """

    @pytest.mark.parametrize("typed", [
        "110+12p",
        "110 + 12p",
        "12p + 110",
        "12p+110",
        "110+12*p",
    ])
    def test_either_term_order_is_accepted(self, typed):
        assert is_reordered_expression_correct(typed, "12p + 110") is True

    @pytest.mark.parametrize("typed", [
        "110 + 11p",     # wrong coefficient
        "12p - 110",     # wrong sign
        "12p + 100",     # wrong constant
        "110 + 12",      # variable dropped
        "12q + 110",     # wrong variable
        "110 + 12p + 1",  # extra term
    ])
    def test_a_different_expression_is_still_wrong(self, typed):
        assert is_reordered_expression_correct(typed, "12p + 110") is False

    def test_unsimplified_work_is_still_wrong(self):
        # The fallback forgives term ORDER only — it never marks work the
        # student was asked to finish as correct.
        assert is_reordered_expression_correct("6p + 6p + 110", "12p + 110") is False
        assert is_reordered_expression_correct("2(6p + 55)", "12p + 110") is False

    @pytest.mark.parametrize("typed,correct", [
        ("felt", "left"),          # same letters, different word
        ("was", "saw"),
        ("fifty-three", "three-fifty"),
        ("63, 54", "54, 63"),      # "write these in order" stays ordered
        ("1/4 2", "2 1/4"),
    ])
    def test_word_and_ordered_answers_are_not_reordered(self, typed, correct):
        # The polynomial parser reads a run of letters as a product of
        # single-letter variables, so the guard must keep worded answers out.
        assert is_reordered_expression_correct(typed, correct) is False

    @pytest.mark.parametrize("typed,correct", [
        ("12-3p", "-3p+12"),        # constant first
        ("-3p+12", "12-3p"),        # negative term first
        ("12 - 3p", "-3p + 12"),
        ("-x+5", "5-x"),
        ("-15-7x+2x^2", "2x^2-7x-15"),
    ])
    def test_a_negative_term_may_lead_either_side(self, typed, correct):
        # The sign travels with its term, so subtraction reorders too.
        assert is_reordered_expression_correct(typed, correct) is True

    @pytest.mark.parametrize("typed", ["3p+12", "12+3p", "-12-3p", "3p-12"])
    def test_moving_a_sign_is_a_different_expression(self, typed):
        assert is_reordered_expression_correct(typed, "12-3p") is False

    def test_alternatives_are_each_tried(self):
        assert is_reordered_expression_correct("110 + 12p", "12p + 110|110 + 12p") is True

    @pytest.mark.parametrize("text,expected", [
        ("12p + 110", True),
        ("2x^2 - 7x - 15", True),
        ("x + y", True),
        ("12p", False),          # one term: nothing to reorder
        ("felt", False),         # word
        ("3(x + 2)", False),     # brackets
        ("", False),
    ])
    def test_simple_expression_guard(self, text, expected):
        assert _is_simple_expression(text) is expected
