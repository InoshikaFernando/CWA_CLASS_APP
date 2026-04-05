"""
Unit tests for currency FK fields and cascade resolution logic (CPP-158, CPP-159).

Covers:
- School.default_currency FK (nullable, SET_NULL)
- Department.currency_override FK (nullable, SET_NULL)
- ClassRoom.currency_override FK (nullable, SET_NULL)
- School.get_effective_currency()  → own → USD fallback
- Department.get_effective_currency() → own → school → USD
- ClassRoom.get_effective_currency() → own → dept → school → USD
- All-null cascade returns USD
- SET_NULL: deleting the currency nulls the FK, method still falls back to USD
"""

from django.test import TestCase

from classroom.models import ClassRoom, Currency, Department, School

# ---------------------------------------------------------------------------
# Test-only currency codes (avoid conflicts with seeded currencies like USD,
# NZD, AUD, etc.  The seed migration runs once per DB; TestCase wraps each
# test in a transaction so test-created rows are rolled back, but the seeded
# rows persist between tests.)
# ---------------------------------------------------------------------------
_A = "XA1"   # first test currency
_B = "XB2"   # second test currency
_C = "XC3"   # third test currency


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _school(**kwargs):
    """Create a minimal School (no admin user required)."""
    defaults = dict(name="Test School", slug="test-school")
    defaults.update(kwargs)
    return School.objects.create(**defaults)


def _department(school, **kwargs):
    """Create a minimal Department."""
    defaults = dict(name="Mathematics", slug="mathematics")
    defaults.update(kwargs)
    return Department.objects.create(school=school, **defaults)


def _classroom(school, department=None, **kwargs):
    """Create a minimal ClassRoom."""
    defaults = dict(name="Year 7 Maths")
    defaults.update(kwargs)
    return ClassRoom.objects.create(school=school, department=department, **defaults)


def _currency(code=_A, name="Test Currency", symbol="$", symbol_position="before", decimal_places=2):
    return Currency.objects.create(
        code=code, name=name, symbol=symbol,
        symbol_position=symbol_position, decimal_places=decimal_places,
    )


# ---------------------------------------------------------------------------
# FK field presence (CPP-158)
# ---------------------------------------------------------------------------

class SchoolCurrencyFKTest(TestCase):
    """School.default_currency FK is nullable and uses SET_NULL."""

    def test_default_currency_is_null_by_default(self):
        school = _school()
        self.assertIsNone(school.default_currency_id)

    def test_can_assign_currency(self):
        cur = _currency(_A)
        school = _school(default_currency=cur)
        school.refresh_from_db()
        self.assertEqual(school.default_currency_id, _A)

    def test_set_null_on_currency_delete(self):
        cur = _currency(_A)
        school = _school(default_currency=cur)
        cur.delete()
        school.refresh_from_db()
        self.assertIsNone(school.default_currency_id)


class DepartmentCurrencyFKTest(TestCase):
    """Department.currency_override FK is nullable and uses SET_NULL."""

    def test_currency_override_is_null_by_default(self):
        school = _school()
        dept = _department(school)
        self.assertIsNone(dept.currency_override_id)

    def test_can_assign_currency(self):
        cur = _currency(_A)
        school = _school()
        dept = _department(school, currency_override=cur)
        dept.refresh_from_db()
        self.assertEqual(dept.currency_override_id, _A)

    def test_set_null_on_currency_delete(self):
        cur = _currency(_A)
        school = _school()
        dept = _department(school, currency_override=cur)
        cur.delete()
        dept.refresh_from_db()
        self.assertIsNone(dept.currency_override_id)


class ClassRoomCurrencyFKTest(TestCase):
    """ClassRoom.currency_override FK is nullable and uses SET_NULL."""

    def test_currency_override_is_null_by_default(self):
        school = _school()
        dept = _department(school)
        room = _classroom(school, dept)
        self.assertIsNone(room.currency_override_id)

    def test_can_assign_currency(self):
        cur = _currency(_A, symbol="£")
        school = _school()
        dept = _department(school)
        room = _classroom(school, dept, currency_override=cur)
        room.refresh_from_db()
        self.assertEqual(room.currency_override_id, _A)

    def test_set_null_on_currency_delete(self):
        cur = _currency(_A, symbol="£")
        school = _school()
        dept = _department(school)
        room = _classroom(school, dept, currency_override=cur)
        cur.delete()
        room.refresh_from_db()
        self.assertIsNone(room.currency_override_id)


# ---------------------------------------------------------------------------
# School.get_effective_currency() (CPP-159)
# ---------------------------------------------------------------------------

_USD_DEFAULTS = dict(
    name='US Dollar', symbol='$', symbol_position='before', decimal_places=2,
)


class SchoolGetEffectiveCurrencyTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Ensure USD exists whether or not the seed migration has run
        Currency.objects.get_or_create(code='USD', defaults=_USD_DEFAULTS)

    def test_returns_own_currency_when_set(self):
        cur = _currency(_A)
        school = _school(default_currency=cur)
        self.assertEqual(school.get_effective_currency().code, _A)

    def test_falls_back_to_usd_when_null(self):
        """USD is seeded by data migration; should be returned when school has no override."""
        school = _school()
        result = school.get_effective_currency()
        self.assertIsNotNone(result)
        self.assertEqual(result.code, "USD")

    def test_returns_none_when_null_and_no_usd(self):
        # Delete USD within this transaction (rolled back after test)
        Currency.objects.filter(code="USD").delete()
        school = _school()
        self.assertIsNone(school.get_effective_currency())

    def test_returns_usd_after_own_currency_deleted(self):
        cur = _currency(_A)
        school = _school(default_currency=cur)
        cur.delete()
        school.refresh_from_db()
        result = school.get_effective_currency()
        self.assertEqual(result.code, "USD")


# ---------------------------------------------------------------------------
# Department.get_effective_currency() (CPP-159)
# ---------------------------------------------------------------------------

class DepartmentGetEffectiveCurrencyTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        Currency.objects.get_or_create(code='USD', defaults=_USD_DEFAULTS)

    def test_returns_own_override_when_set(self):
        own = _currency(_A)
        school_cur = _currency(_B)
        school = _school(default_currency=school_cur)
        dept = _department(school, currency_override=own)
        self.assertEqual(dept.get_effective_currency().code, _A)

    def test_inherits_from_school_when_own_is_null(self):
        school_cur = _currency(_A)
        school = _school(default_currency=school_cur)
        dept = _department(school)
        self.assertEqual(dept.get_effective_currency().code, _A)

    def test_falls_back_to_usd_when_both_null(self):
        school = _school()
        dept = _department(school)
        result = dept.get_effective_currency()
        self.assertIsNotNone(result)
        self.assertEqual(result.code, "USD")

    def test_dept_override_wins_over_school(self):
        dept_cur = _currency(_A)
        school_cur = _currency(_B)
        school = _school(default_currency=school_cur)
        dept = _department(school, currency_override=dept_cur)
        self.assertEqual(dept.get_effective_currency().code, _A)


# ---------------------------------------------------------------------------
# ClassRoom.get_effective_currency() (CPP-159)
# ---------------------------------------------------------------------------

class ClassRoomGetEffectiveCurrencyTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        Currency.objects.get_or_create(code='USD', defaults=_USD_DEFAULTS)

    def test_returns_own_override_when_set(self):
        cls_cur = _currency(_A)
        dept_cur = _currency(_B)
        sch_cur = _currency(_C)
        school = _school(default_currency=sch_cur)
        dept = _department(school, currency_override=dept_cur)
        room = _classroom(school, dept, currency_override=cls_cur)
        self.assertEqual(room.get_effective_currency().code, _A)

    def test_inherits_from_department_when_own_null(self):
        dept_cur = _currency(_A)
        sch_cur = _currency(_B)
        school = _school(default_currency=sch_cur)
        dept = _department(school, currency_override=dept_cur)
        room = _classroom(school, dept)
        self.assertEqual(room.get_effective_currency().code, _A)

    def test_inherits_from_school_when_dept_also_null(self):
        sch_cur = _currency(_A)
        school = _school(default_currency=sch_cur)
        dept = _department(school)
        room = _classroom(school, dept)
        self.assertEqual(room.get_effective_currency().code, _A)

    def test_falls_back_to_usd_when_all_null(self):
        school = _school()
        dept = _department(school)
        room = _classroom(school, dept)
        result = room.get_effective_currency()
        self.assertIsNotNone(result)
        self.assertEqual(result.code, "USD")

    def test_returns_none_when_all_null_and_no_usd(self):
        Currency.objects.filter(code="USD").delete()
        school = _school()
        dept = _department(school)
        room = _classroom(school, dept)
        self.assertIsNone(room.get_effective_currency())

    def test_class_override_wins_over_dept_and_school(self):
        cls_cur = _currency(_A)
        dept_cur = _currency(_B)
        sch_cur = _currency(_C)
        school = _school(default_currency=sch_cur)
        dept = _department(school, currency_override=dept_cur)
        room = _classroom(school, dept, currency_override=cls_cur)
        self.assertEqual(room.get_effective_currency().code, _A)

    def test_no_department_falls_back_to_school(self):
        sch_cur = _currency(_A)
        school = _school(default_currency=sch_cur)
        room = _classroom(school, department=None)
        self.assertEqual(room.get_effective_currency().code, _A)

    def test_no_dept_no_school_falls_back_to_usd(self):
        room = ClassRoom.objects.create(name="Orphan Class", school=None, department=None)
        result = room.get_effective_currency()
        self.assertIsNotNone(result)
        self.assertEqual(result.code, "USD")

    def test_deleted_class_override_inherits_from_dept(self):
        cls_cur = _currency(_A)
        dept_cur = _currency(_B)
        school = _school()
        dept = _department(school, currency_override=dept_cur)
        room = _classroom(school, dept, currency_override=cls_cur)
        cls_cur.delete()
        room.refresh_from_db()
        self.assertEqual(room.get_effective_currency().code, _B)
