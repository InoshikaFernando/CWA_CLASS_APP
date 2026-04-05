"""
Unit tests for CPP-164: Currency deactivation guard rails.

Rules enforced by Currency.clean():
- If a currency is referenced by any School.default_currency,
  Department.currency_override, or ClassRoom.currency_override it
  cannot be set is_active=False.
- Currencies with no references can be deactivated freely.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import ClassRoom, Currency, Department, School

# Test-only codes (no conflict with seeded currencies)
_USED = "XU1"
_FREE = "XF2"


def _currency(code, **kwargs):
    defaults = dict(name="Test Currency", symbol="$", symbol_position="before", decimal_places=2)
    defaults.update(kwargs)
    return Currency.objects.create(code=code, **defaults)


def _school(**kwargs):
    defaults = dict(name="Test School", slug="test-school")
    defaults.update(kwargs)
    return School.objects.create(**defaults)


def _department(school, **kwargs):
    defaults = dict(name="Maths", slug="maths")
    defaults.update(kwargs)
    return Department.objects.create(school=school, **defaults)


def _classroom(school, **kwargs):
    defaults = dict(name="Year 7")
    defaults.update(kwargs)
    return ClassRoom.objects.create(school=school, **defaults)


class CurrencyDeactivateUnreferencedTest(TestCase):
    """Currencies with no references can be freely deactivated."""

    def test_unused_currency_can_be_deactivated(self):
        cur = _currency(_FREE)
        cur.is_active = False
        cur.clean()          # must not raise
        cur.save()
        self.assertFalse(Currency.objects.get(code=_FREE).is_active)

    def test_already_inactive_currency_stays_inactive(self):
        cur = _currency(_FREE, is_active=False)
        cur.is_active = False
        cur.clean()          # no change; must not raise
        cur.save()
        self.assertFalse(Currency.objects.get(code=_FREE).is_active)

    def test_activating_referenced_currency_is_allowed(self):
        """Re-activating a currency that is referenced should never be blocked."""
        cur = _currency(_USED, is_active=False)
        school = _school()
        # FK is SET_NULL on delete; we can still set the FK directly even when inactive
        school.default_currency = cur
        school.save()
        cur.is_active = True
        cur.clean()          # must not raise
        cur.save()
        self.assertTrue(Currency.objects.get(code=_USED).is_active)


class CurrencyDeactivateSchoolReferenceTest(TestCase):
    """Deactivating a currency used by a School is blocked."""

    def test_school_default_currency_blocks_deactivation(self):
        cur = _currency(_USED)
        school = _school(default_currency=cur)  # noqa: F841
        cur.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            cur.clean()
        self.assertIn("Test School", str(ctx.exception))

    def test_error_message_mentions_school_name(self):
        cur = _currency(_USED)
        _school(name="Greenfield Academy", slug="greenfield", default_currency=cur)
        cur.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            cur.clean()
        self.assertIn("Greenfield Academy", str(ctx.exception))


class CurrencyDeactivateDepartmentReferenceTest(TestCase):
    """Deactivating a currency used by a Department is blocked."""

    def test_dept_override_blocks_deactivation(self):
        cur = _currency(_USED)
        school = _school()
        _department(school, currency_override=cur)
        cur.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            cur.clean()
        self.assertIn("Maths", str(ctx.exception))

    def test_multiple_depts_all_listed(self):
        cur = _currency(_USED)
        school = _school()
        _department(school, name="Science", slug="science", currency_override=cur)
        _department(school, name="English", slug="english", currency_override=cur)
        cur.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            cur.clean()
        error_msg = str(ctx.exception)
        self.assertIn("Science", error_msg)
        self.assertIn("English", error_msg)


class CurrencyDeactivateClassRoomReferenceTest(TestCase):
    """Deactivating a currency used by a ClassRoom is blocked."""

    def test_classroom_override_blocks_deactivation(self):
        cur = _currency(_USED)
        school = _school()
        _classroom(school, name="Year 9 Maths", currency_override=cur)
        cur.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            cur.clean()
        self.assertIn("Year 9 Maths", str(ctx.exception))


class CurrencyDeactivateMultipleReferencesTest(TestCase):
    """When currency is used across school/dept/class, all are listed."""

    def test_all_reference_types_appear_in_error(self):
        cur = _currency(_USED)
        school = _school(default_currency=cur)
        dept = _department(school, currency_override=cur)  # noqa: F841
        _classroom(school, name="Year 10", currency_override=cur)

        cur.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            cur.clean()
        error_msg = str(ctx.exception)
        self.assertIn("Test School", error_msg)
        self.assertIn("Maths", error_msg)
        self.assertIn("Year 10", error_msg)
