"""
Unit tests for the Currency model (CPP-157).

Covers:
- __str__ format: "CODE - Name"
- is_active default is True
- decimal_places default is 2
- symbol_position choices
- Currency.format_amount() helper
- format_currency template filter (with and without a Currency instance)
- is_active=False hides currency from active queryset
"""

from decimal import Decimal

from django.test import TestCase

from classroom.models import Currency
from classroom.templatetags.classroom_extras import format_currency


class CurrencyStrTest(TestCase):
    """Currency.__str__ returns 'CODE - Name'."""

    def test_standard_currency(self):
        c = Currency(code="NZD", name="New Zealand Dollar",
                     symbol="$", symbol_position="before", decimal_places=2)
        self.assertEqual(str(c), "NZD - New Zealand Dollar")

    def test_zero_decimal_currency(self):
        c = Currency(code="JPY", name="Japanese Yen",
                     symbol="¥", symbol_position="before", decimal_places=0)
        self.assertEqual(str(c), "JPY - Japanese Yen")

    def test_after_position_currency(self):
        c = Currency(code="SEK", name="Swedish Krona",
                     symbol="kr", symbol_position="after", decimal_places=2)
        self.assertEqual(str(c), "SEK - Swedish Krona")


class CurrencyDefaultsTest(TestCase):
    """Currency model field defaults."""

    def setUp(self):
        self.currency = Currency.objects.create(
            code="TST",
            name="Test Dollar",
            symbol="T",
            symbol_position=Currency.SYMBOL_BEFORE,
        )

    def test_is_active_defaults_to_true(self):
        self.assertTrue(self.currency.is_active)

    def test_decimal_places_defaults_to_two(self):
        self.assertEqual(self.currency.decimal_places, 2)

    def test_symbol_position_default_is_before(self):
        self.assertEqual(self.currency.symbol_position, Currency.SYMBOL_BEFORE)


class CurrencyFormatAmountTest(TestCase):
    """Currency.format_amount() formats a Decimal/float correctly."""

    def test_before_symbol_two_decimals(self):
        c = Currency(code="NZD", name="New Zealand Dollar",
                     symbol="$", symbol_position="before", decimal_places=2)
        self.assertEqual(c.format_amount(Decimal("99.50")), "$99.50")

    def test_before_symbol_zero_decimals(self):
        c = Currency(code="JPY", name="Japanese Yen",
                     symbol="¥", symbol_position="before", decimal_places=0)
        self.assertEqual(c.format_amount(Decimal("1500")), "¥1500")

    def test_after_symbol(self):
        c = Currency(code="SEK", name="Swedish Krona",
                     symbol="kr", symbol_position="after", decimal_places=2)
        self.assertEqual(c.format_amount(Decimal("250.00")), "250.00\u00a0kr")

    def test_zero_amount(self):
        c = Currency(code="USD", name="US Dollar",
                     symbol="$", symbol_position="before", decimal_places=2)
        self.assertEqual(c.format_amount(Decimal("0")), "$0.00")

    def test_integer_input(self):
        c = Currency(code="GBP", name="British Pound",
                     symbol="£", symbol_position="before", decimal_places=2)
        self.assertEqual(c.format_amount(100), "£100.00")

    def test_float_input(self):
        c = Currency(code="EUR", name="Euro",
                     symbol="€", symbol_position="before", decimal_places=2)
        self.assertEqual(c.format_amount(19.99), "€19.99")


class CurrencyActiveQuerysetTest(TestCase):
    """Deactivating a currency hides it from active-only queries."""

    def setUp(self):
        self.active = Currency.objects.create(
            code="ACT", name="Active Currency", symbol="A",
            symbol_position="before", decimal_places=2, is_active=True,
        )
        self.inactive = Currency.objects.create(
            code="INA", name="Inactive Currency", symbol="I",
            symbol_position="before", decimal_places=2, is_active=False,
        )

    def test_active_currency_appears_in_active_filter(self):
        qs = Currency.objects.filter(is_active=True)
        self.assertIn(self.active, qs)

    def test_inactive_currency_excluded_from_active_filter(self):
        qs = Currency.objects.filter(is_active=True)
        self.assertNotIn(self.inactive, qs)

    def test_inactive_currency_still_exists_in_db(self):
        """Deactivated currencies are soft-hidden, not deleted."""
        self.assertTrue(Currency.objects.filter(code="INA").exists())

    def test_toggle_active_to_inactive(self):
        self.active.is_active = False
        self.active.save(update_fields=["is_active"])
        self.assertFalse(Currency.objects.get(code="ACT").is_active)

    def test_toggle_inactive_to_active(self):
        self.inactive.is_active = True
        self.inactive.save(update_fields=["is_active"])
        self.assertTrue(Currency.objects.get(code="INA").is_active)


class FormatCurrencyFilterTest(TestCase):
    """format_currency template filter — fallback and currency-aware paths."""

    # ---- fallback (no currency) ------------------------------------------

    def test_fallback_two_decimals(self):
        self.assertEqual(format_currency(Decimal("99.50")), "$99.50")

    def test_fallback_none_currency(self):
        self.assertEqual(format_currency(Decimal("10.00"), None), "$10.00")

    def test_fallback_zero_value(self):
        self.assertEqual(format_currency(Decimal("0")), "$0.00")

    def test_fallback_int_value(self):
        self.assertEqual(format_currency(100), "$100.00")

    def test_fallback_float_value(self):
        self.assertEqual(format_currency(19.99), "$19.99")

    def test_none_value_returns_empty(self):
        self.assertEqual(format_currency(None), "")

    # ---- with Currency instance -----------------------------------------

    def test_before_symbol(self):
        nzd = Currency(code="NZD", name="New Zealand Dollar",
                       symbol="$", symbol_position="before", decimal_places=2)
        self.assertEqual(format_currency(Decimal("120.50"), nzd), "$120.50")

    def test_zero_decimal_places(self):
        jpy = Currency(code="JPY", name="Japanese Yen",
                       symbol="¥", symbol_position="before", decimal_places=0)
        self.assertEqual(format_currency(Decimal("1500"), jpy), "¥1500")

    def test_after_symbol_uses_nbsp(self):
        sek = Currency(code="SEK", name="Swedish Krona",
                       symbol="kr", symbol_position="after", decimal_places=2)
        self.assertEqual(format_currency(Decimal("250.00"), sek), "250.00\u00a0kr")

    def test_gbp_before_symbol(self):
        gbp = Currency(code="GBP", name="British Pound",
                       symbol="£", symbol_position="before", decimal_places=2)
        self.assertEqual(format_currency(Decimal("49.99"), gbp), "£49.99")


class CurrencyOrderingTest(TestCase):
    """Currencies are ordered by code by default."""

    def setUp(self):
        Currency.objects.create(code="ZZZ", name="Z Currency", symbol="Z",
                                symbol_position="before", decimal_places=2)
        Currency.objects.create(code="AAA", name="A Currency", symbol="A",
                                symbol_position="before", decimal_places=2)
        Currency.objects.create(code="MMM", name="M Currency", symbol="M",
                                symbol_position="before", decimal_places=2)

    def test_default_ordering_is_by_code(self):
        codes = list(
            Currency.objects.filter(code__in=["ZZZ", "AAA", "MMM"])
            .values_list("code", flat=True)
        )
        self.assertEqual(codes, ["AAA", "MMM", "ZZZ"])
