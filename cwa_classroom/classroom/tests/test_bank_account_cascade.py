"""
Unit tests for bank account number & GST cascade resolution (CPP-185).

Covers:
- School.get_resolved_account_number() / get_resolved_gst()
- Department.get_resolved_account_number() → own → school
- Department.get_resolved_gst() → always delegates to school
- ClassRoom.get_resolved_account_number() → own → dept → school → None
- ClassRoom.get_resolved_gst() → delegates through dept → school → None
- All-null cascade returns None (no account section on invoice)
- Clearing a department override reverts to school default dynamically
- Nullable fields: NULL and "" are both treated as "no override"
"""

from django.test import TestCase

from classroom.models import ClassRoom, Department, School


# ---------------------------------------------------------------------------
# Helpers — minimal object creation without requiring auth users
# ---------------------------------------------------------------------------

def _school(name="Test School", slug="test-school", **kwargs):
    return School.objects.create(name=name, slug=slug, **kwargs)


def _department(school, name="Mathematics", slug="mathematics", **kwargs):
    return Department.objects.create(school=school, name=name, slug=slug, **kwargs)


def _classroom(school, department=None, name="Year 7 Maths", **kwargs):
    return ClassRoom.objects.create(school=school, department=department, name=name, **kwargs)


# ---------------------------------------------------------------------------
# School.get_resolved_account_number / get_resolved_gst
# ---------------------------------------------------------------------------

class SchoolResolutionTests(TestCase):

    def test_school_returns_own_account_number(self):
        school = _school(bank_account_number="12-3456-7890123-00")
        self.assertEqual(school.get_resolved_account_number(), "12-3456-7890123-00")

    def test_school_returns_none_when_account_number_blank(self):
        school = _school(bank_account_number="")
        self.assertIsNone(school.get_resolved_account_number())

    def test_school_returns_none_when_account_number_not_set(self):
        school = _school()
        self.assertIsNone(school.get_resolved_account_number())

    def test_school_returns_own_gst(self):
        school = _school(gst_number="123-456-789")
        self.assertEqual(school.get_resolved_gst(), "123-456-789")

    def test_school_returns_none_when_gst_blank(self):
        school = _school(gst_number="")
        self.assertIsNone(school.get_resolved_gst())

    def test_school_returns_none_when_gst_not_set(self):
        school = _school()
        self.assertIsNone(school.get_resolved_gst())


# ---------------------------------------------------------------------------
# Department.get_resolved_account_number
# ---------------------------------------------------------------------------

class DepartmentAccountResolutionTests(TestCase):

    def test_department_uses_own_override(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="DEPT-ACC")
        self.assertEqual(dept.get_resolved_account_number(), "DEPT-ACC")

    def test_department_falls_back_to_school(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school)  # no override
        self.assertEqual(dept.get_resolved_account_number(), "SCHOOL-ACC")

    def test_department_null_override_falls_back_to_school(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number=None)
        self.assertEqual(dept.get_resolved_account_number(), "SCHOOL-ACC")

    def test_department_empty_string_override_falls_back_to_school(self):
        """Empty string on dept is treated as no override, same as NULL."""
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="")
        self.assertEqual(dept.get_resolved_account_number(), "SCHOOL-ACC")

    def test_all_null_returns_none(self):
        school = _school()  # no account number
        dept = _department(school)
        self.assertIsNone(dept.get_resolved_account_number())


# ---------------------------------------------------------------------------
# Department.get_resolved_gst — always delegates to school
# ---------------------------------------------------------------------------

class DepartmentGstResolutionTests(TestCase):

    def test_department_returns_school_gst(self):
        school = _school(gst_number="GST-999")
        dept = _department(school)
        self.assertEqual(dept.get_resolved_gst(), "GST-999")

    def test_department_returns_none_when_school_gst_not_set(self):
        school = _school()
        dept = _department(school)
        self.assertIsNone(dept.get_resolved_gst())

    def test_department_gst_override_field_does_not_affect_resolved_gst(self):
        """Department.gst_number is a settings-override field used by
        get_effective_settings, but get_resolved_gst() is institute-level only
        — the department's own gst_number field is intentionally bypassed."""
        school = _school(gst_number="SCHOOL-GST")
        # Even if a dept gst_number value is stored (legacy / settings override),
        # get_resolved_gst still returns the school's value.
        dept = _department(school, gst_number="DEPT-GST")
        self.assertEqual(dept.get_resolved_gst(), "SCHOOL-GST")


# ---------------------------------------------------------------------------
# ClassRoom.get_resolved_account_number
# ---------------------------------------------------------------------------

class ClassRoomAccountResolutionTests(TestCase):

    def test_class_uses_own_override(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="DEPT-ACC")
        cls = _classroom(school, department=dept, bank_account_number="CLASS-ACC")
        self.assertEqual(cls.get_resolved_account_number(), "CLASS-ACC")

    def test_class_falls_back_to_department(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="DEPT-ACC")
        cls = _classroom(school, department=dept)
        self.assertEqual(cls.get_resolved_account_number(), "DEPT-ACC")

    def test_class_falls_back_to_school_when_dept_has_no_override(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school)  # no override
        cls = _classroom(school, department=dept)
        self.assertEqual(cls.get_resolved_account_number(), "SCHOOL-ACC")

    def test_class_null_override_falls_back_to_department(self):
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="DEPT-ACC")
        cls = _classroom(school, department=dept, bank_account_number=None)
        self.assertEqual(cls.get_resolved_account_number(), "DEPT-ACC")

    def test_class_empty_string_override_falls_back_to_department(self):
        """Empty string on class is treated as no override."""
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="DEPT-ACC")
        cls = _classroom(school, department=dept, bank_account_number="")
        self.assertEqual(cls.get_resolved_account_number(), "DEPT-ACC")

    def test_all_null_returns_none(self):
        """If no level has an account number, None is returned — no section on invoice."""
        school = _school()
        dept = _department(school)
        cls = _classroom(school, department=dept)
        self.assertIsNone(cls.get_resolved_account_number())

    def test_class_without_department_falls_back_to_school(self):
        """ClassRoom can exist without a department — falls back directly to school."""
        school = _school(bank_account_number="SCHOOL-ACC")
        cls = _classroom(school, department=None)
        self.assertEqual(cls.get_resolved_account_number(), "SCHOOL-ACC")

    def test_class_without_department_or_school_returns_none(self):
        cls = ClassRoom.objects.create(name="Orphan Class", school=None, department=None)
        self.assertIsNone(cls.get_resolved_account_number())

    def test_clearing_department_override_reverts_to_school(self):
        """Removing a dept override dynamically reverts child classes (no save needed)."""
        school = _school(bank_account_number="SCHOOL-ACC")
        dept = _department(school, bank_account_number="DEPT-ACC")
        cls = _classroom(school, department=dept)
        # Initially resolves to dept override
        self.assertEqual(cls.get_resolved_account_number(), "DEPT-ACC")
        # Clear the dept override (simulate HoI clearing it)
        dept.bank_account_number = None
        dept.save(update_fields=["bank_account_number"])
        dept.refresh_from_db()
        # Now resolves to school default — no class data change needed
        self.assertEqual(cls.get_resolved_account_number(), "SCHOOL-ACC")


# ---------------------------------------------------------------------------
# ClassRoom.get_resolved_gst
# ---------------------------------------------------------------------------

class ClassRoomGstResolutionTests(TestCase):

    def test_class_returns_school_gst_via_department(self):
        school = _school(gst_number="GST-001")
        dept = _department(school)
        cls = _classroom(school, department=dept)
        self.assertEqual(cls.get_resolved_gst(), "GST-001")

    def test_class_without_department_returns_school_gst(self):
        school = _school(gst_number="GST-001")
        cls = _classroom(school, department=None)
        self.assertEqual(cls.get_resolved_gst(), "GST-001")

    def test_class_returns_none_when_school_gst_not_set(self):
        school = _school()
        dept = _department(school)
        cls = _classroom(school, department=dept)
        self.assertIsNone(cls.get_resolved_gst())

    def test_class_without_school_or_department_returns_none(self):
        cls = ClassRoom.objects.create(name="Orphan Class", school=None, department=None)
        self.assertIsNone(cls.get_resolved_gst())


# ---------------------------------------------------------------------------
# Full resolution chain — combined scenarios matching invoice display rules
# ---------------------------------------------------------------------------

class InvoiceDisplayRuleTests(TestCase):
    """
    Verify the four display rules described in CPP-185:
      1. account number AND gst  → show both
      2. account number, no gst  → show account only
      3. no account number, gst  → show gst only
      4. neither                 → show nothing
    """

    def setUp(self):
        self.school = _school(bank_account_number="12-3456-7890", gst_number="GST-XYZ")
        self.dept = _department(self.school)
        self.cls = _classroom(self.school, department=self.dept)

    def test_rule_1_both_set(self):
        acc = self.cls.get_resolved_account_number()
        gst = self.cls.get_resolved_gst()
        self.assertIsNotNone(acc)
        self.assertIsNotNone(gst)

    def test_rule_2_account_only(self):
        self.school.gst_number = ""
        self.school.save(update_fields=["gst_number"])
        acc = self.cls.get_resolved_account_number()
        gst = self.cls.get_resolved_gst()
        self.assertIsNotNone(acc)
        self.assertIsNone(gst)

    def test_rule_3_gst_only(self):
        self.school.bank_account_number = ""
        self.school.save(update_fields=["bank_account_number"])
        acc = self.cls.get_resolved_account_number()
        gst = self.cls.get_resolved_gst()
        self.assertIsNone(acc)
        self.assertIsNotNone(gst)

    def test_rule_4_neither(self):
        self.school.bank_account_number = ""
        self.school.gst_number = ""
        self.school.save(update_fields=["bank_account_number", "gst_number"])
        acc = self.cls.get_resolved_account_number()
        gst = self.cls.get_resolved_gst()
        self.assertIsNone(acc)
        self.assertIsNone(gst)
