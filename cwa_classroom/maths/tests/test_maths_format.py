"""Unit tests for the maths_format template filters (display-only)."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from maths.templatetags.maths_format import credit_state, exponents


class ExponentsFilterTests(SimpleTestCase):
    def test_scientific_notation(self):
        self.assertEqual(
            exponents('2 × 10^5 × 9.8 × 10^-4'),
            '2 × 10⁵ × 9.8 × 10⁻⁴',
        )

    def test_single_and_multi_digit_exponents(self):
        self.assertEqual(exponents('x^2 + y^10'), 'x² + y¹⁰')

    def test_negative_and_positive_signs(self):
        self.assertEqual(exponents('10^-4'), '10⁻⁴')
        self.assertEqual(exponents('10^+4'), '10⁺⁴')

    def test_double_star_form(self):
        self.assertEqual(exponents('3 cm**3'), '3 cm³')

    def test_whitespace_after_caret_is_tolerated(self):
        self.assertEqual(exponents('10^ 5'), '10⁵')

    def test_text_without_exponents_is_unchanged(self):
        self.assertEqual(exponents('Express in scientific notation'),
                         'Express in scientific notation')

    def test_caret_not_followed_by_digits_is_left_alone(self):
        # A stray caret with no exponent must not be mangled.
        self.assertEqual(exponents('a ^ b'), 'a ^ b')

    def test_empty_and_none(self):
        self.assertEqual(exponents(''), '')
        self.assertIsNone(exponents(None))


class CreditStateFilterTests(SimpleTestCase):
    """Display tiers for AI-graded answers: full=1.0, partial>=0.75, else wrong.

    The floor is the grader's own pass mark, so a review page and the quiz
    that produced the score cannot put the same answer in different bands.
    """

    def _ans(self, frac=None, is_correct=False):
        return SimpleNamespace(ai_score_fraction=frac, is_correct=is_correct)

    def test_full_marks_is_correct(self):
        self.assertEqual(credit_state(self._ans(frac=1.0, is_correct=True)), 'correct')

    def test_high_but_not_full_score_is_partial(self):
        # A 0.85 answer previously showed as fully correct — now "partially correct".
        self.assertEqual(credit_state(self._ans(frac=0.85, is_correct=True)), 'partial')

    def test_score_at_partial_floor_is_partial(self):
        self.assertEqual(credit_state(self._ans(frac=0.75)), 'partial')

    def test_score_just_below_floor_is_wrong(self):
        self.assertEqual(credit_state(self._ans(frac=0.74)), 'wrong')

    def test_a_mid_range_score_is_wrong_not_partial(self):
        # Half an answer earns nothing now: below the pass mark it is wrong.
        self.assertEqual(credit_state(self._ans(frac=0.5)), 'wrong')

    def test_zero_score_is_wrong(self):
        self.assertEqual(credit_state(self._ans(frac=0.0)), 'wrong')

    def test_non_ai_answer_falls_back_to_is_correct(self):
        # No ai_score_fraction (MCQ / exact-match) — never "partial".
        self.assertEqual(credit_state(self._ans(frac=None, is_correct=True)), 'correct')
        self.assertEqual(credit_state(self._ans(frac=None, is_correct=False)), 'wrong')
