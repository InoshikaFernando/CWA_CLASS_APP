"""Unit tests for the maths_format template filters (display-only)."""
from django.test import SimpleTestCase

from maths.templatetags.maths_format import exponents


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
