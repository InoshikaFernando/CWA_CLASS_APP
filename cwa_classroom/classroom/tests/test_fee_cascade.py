"""
Unit tests for the fee cascade resolution (get_effective_fee_for_class / _for_student).

Cascade order (first non-NULL wins):
  1. ClassStudent.fee_override
  2. ClassRoom.fee_override
  3. DepartmentLevel.fee_override
  4. DepartmentSubject.fee_override
  5. Department.default_fee
  6. School.default_fee   ← extended in CPP-185

Covers:
- School.default_fee is returned when all lower levels are None/unset
- School.default_fee is NOT returned when dept/class/level/subject has a fee
- Clearing dept fee falls back to school default
- School.default_fee=None → 'No fee set' is returned
- _get_class_fee_source() returns 'School default' correctly
- get_parent_fee_for_class/subject/level all walk up to school
"""

from decimal import Decimal

from django.test import TestCase

from classroom.fee_utils import (
    _get_class_fee_source,
    get_effective_fee_for_class,
    get_effective_fee_for_student,
    get_parent_fee_for_class,
    get_parent_fee_for_level,
    get_parent_fee_for_subject,
)
from classroom.models import (
    ClassRoom,
    ClassStudent,
    Department,
    DepartmentLevel,
    DepartmentSubject,
    Level,
    School,
    Subject,
)

# ---------------------------------------------------------------------------
# Minimal object factories
# ---------------------------------------------------------------------------

def _school(name="Test School", slug="ts", **kwargs):
    return School.objects.create(name=name, slug=slug, **kwargs)


def _dept(school, name="Music", slug="music", **kwargs):
    return Department.objects.create(school=school, name=name, slug=slug, **kwargs)


def _classroom(school, dept=None, name="Guitar 01", **kwargs):
    return ClassRoom.objects.create(school=school, department=dept, name=name, **kwargs)


import itertools
_level_counter = itertools.count(300)


def _subject(name="Guitar", slug=None, **kwargs):
    slug = slug or name.lower().replace(" ", "-")
    return Subject.objects.create(name=name, slug=slug, **kwargs)


def _level(display_name="Beginner", subject=None, **kwargs):
    level_number = kwargs.pop("level_number", next(_level_counter))
    return Level.objects.create(
        level_number=level_number, display_name=display_name, subject=subject, **kwargs
    )


# ---------------------------------------------------------------------------
# School.default_fee as ultimate fallback via get_effective_fee_for_class
# ---------------------------------------------------------------------------

class SchoolDefaultFeeCascadeTests(TestCase):

    def setUp(self):
        self.school = _school(default_fee=Decimal("20.00"))
        self.dept = _dept(self.school)                   # no dept default_fee
        self.cls = _classroom(self.school, self.dept)    # no class fee_override

    def test_school_default_fee_returned_when_no_lower_fee(self):
        fee = get_effective_fee_for_class(self.cls)
        self.assertEqual(fee, Decimal("20.00"))

    def test_class_override_takes_priority_over_school_default(self):
        self.cls.fee_override = Decimal("50.00")
        self.cls.save()
        fee = get_effective_fee_for_class(self.cls)
        self.assertEqual(fee, Decimal("50.00"))

    def test_dept_default_takes_priority_over_school_default(self):
        self.dept.default_fee = Decimal("35.00")
        self.dept.save()
        fee = get_effective_fee_for_class(self.cls)
        self.assertEqual(fee, Decimal("35.00"))

    def test_school_default_returned_when_dept_default_cleared(self):
        self.dept.default_fee = Decimal("35.00")
        self.dept.save()
        # clear dept fee → should fall back to school
        self.dept.default_fee = None
        self.dept.save()
        fee = get_effective_fee_for_class(self.cls)
        self.assertEqual(fee, Decimal("20.00"))

    def test_none_returned_when_school_default_also_none(self):
        self.school.default_fee = None
        self.school.save()
        fee = get_effective_fee_for_class(self.cls)
        self.assertIsNone(fee)

    def test_school_default_fee_works_without_department(self):
        """Class with no department at all still gets school default."""
        cls_no_dept = _classroom(self.school, dept=None, name="Orphan Class")
        fee = get_effective_fee_for_class(cls_no_dept)
        self.assertEqual(fee, Decimal("20.00"))


class SchoolDefaultFeeSubjectLevelPriorityTests(TestCase):

    def setUp(self):
        self.school = _school(default_fee=Decimal("20.00"))
        self.subject = _subject()
        self.dept = _dept(self.school)
        self.cls = _classroom(self.school, self.dept, subject=self.subject)

    def test_subject_fee_takes_priority_over_school_default(self):
        DepartmentSubject.objects.create(
            department=self.dept,
            subject=self.subject,
            fee_override=Decimal("45.00"),
        )
        fee = get_effective_fee_for_class(self.cls)
        self.assertEqual(fee, Decimal("45.00"))

    def test_level_fee_takes_priority_over_school_default(self):
        level = _level(display_name="Beginner", subject=self.subject)
        DepartmentLevel.objects.create(
            department=self.dept,
            level=level,
            fee_override=Decimal("30.00"),
        )
        self.cls.levels.add(level)
        fee = get_effective_fee_for_class(self.cls)
        self.assertEqual(fee, Decimal("30.00"))


# ---------------------------------------------------------------------------
# _get_class_fee_source returns 'School default'
# ---------------------------------------------------------------------------

class SchoolDefaultFeeSourceLabelTests(TestCase):

    def test_source_label_is_school_default(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school)
        cls = _classroom(school, dept)
        self.assertEqual(_get_class_fee_source(cls), "School default")

    def test_source_label_is_department_default_when_dept_has_fee(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school, default_fee=Decimal("30.00"))
        cls = _classroom(school, dept)
        self.assertEqual(_get_class_fee_source(cls), "Department default")

    def test_source_label_is_no_fee_set_when_school_also_none(self):
        school = _school()  # no default_fee
        dept = _dept(school)
        cls = _classroom(school, dept)
        self.assertEqual(_get_class_fee_source(cls), "No fee set")

    def test_source_label_is_school_default_for_no_dept_class(self):
        school = _school(default_fee=Decimal("20.00"))
        cls = _classroom(school, dept=None, name="Floating Class")
        self.assertEqual(_get_class_fee_source(cls), "School default")


# ---------------------------------------------------------------------------
# get_effective_fee_for_student delegates to class which reaches school
# ---------------------------------------------------------------------------

class SchoolDefaultFeeForStudentTests(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.school = _school(default_fee=Decimal("25.00"))
        self.dept = _dept(self.school)
        self.cls = _classroom(self.school, self.dept)
        self.student = User.objects.create_user(
            username="student_sf", password="pw", email="s@sf.com"
        )

    def test_student_inherits_school_default_fee(self):
        cs = ClassStudent.objects.create(
            classroom=self.cls,
            student=self.student,
        )
        fee = get_effective_fee_for_student(cs)
        self.assertEqual(fee, Decimal("25.00"))

    def test_student_override_takes_priority_over_school_default(self):
        cs = ClassStudent.objects.create(
            classroom=self.cls,
            student=self.student,
            fee_override=Decimal("10.00"),
        )
        fee = get_effective_fee_for_student(cs)
        self.assertEqual(fee, Decimal("10.00"))


# ---------------------------------------------------------------------------
# get_parent_fee_for_class includes school fallback
# ---------------------------------------------------------------------------

class ParentFeeForClassSchoolFallbackTests(TestCase):

    def test_parent_fee_for_class_returns_school_default(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school)
        cls = _classroom(school, dept)
        fee, label = get_parent_fee_for_class(cls)
        self.assertEqual(fee, Decimal("20.00"))
        self.assertEqual(label, "School default")

    def test_parent_fee_for_class_dept_takes_priority(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school, default_fee=Decimal("35.00"))
        cls = _classroom(school, dept)
        fee, label = get_parent_fee_for_class(cls)
        self.assertEqual(fee, Decimal("35.00"))
        self.assertEqual(label, "Department default")

    def test_parent_fee_for_class_none_when_school_also_none(self):
        school = _school()
        dept = _dept(school)
        cls = _classroom(school, dept)
        fee, label = get_parent_fee_for_class(cls)
        self.assertIsNone(fee)
        self.assertEqual(label, "No fee set")


# ---------------------------------------------------------------------------
# get_parent_fee_for_subject includes school fallback
# ---------------------------------------------------------------------------

class ParentFeeForSubjectSchoolFallbackTests(TestCase):

    def test_school_default_returned_when_dept_has_no_fee(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school)
        fee, label = get_parent_fee_for_subject(dept)
        self.assertEqual(fee, Decimal("20.00"))
        self.assertEqual(label, "School default")

    def test_dept_default_takes_priority_over_school(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school, default_fee=Decimal("40.00"))
        fee, label = get_parent_fee_for_subject(dept)
        self.assertEqual(fee, Decimal("40.00"))
        self.assertEqual(label, "Department default")


# ---------------------------------------------------------------------------
# get_parent_fee_for_level includes school fallback
# ---------------------------------------------------------------------------

class ParentFeeForLevelSchoolFallbackTests(TestCase):

    def test_school_default_returned_when_dept_has_no_fee(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school)
        subject = _subject(name="Piano")
        level = _level(display_name="Beginner Piano", subject=subject)
        dl = DepartmentLevel.objects.create(department=dept, level=level)
        fee, label = get_parent_fee_for_level(dl)
        self.assertEqual(fee, Decimal("20.00"))
        self.assertEqual(label, "School default")

    def test_dept_default_takes_priority_in_level_parent(self):
        school = _school(default_fee=Decimal("20.00"))
        dept = _dept(school, default_fee=Decimal("35.00"))
        subject = _subject(name="Violin")
        level = _level(display_name="Beginner Violin", subject=subject)
        dl = DepartmentLevel.objects.create(department=dept, level=level)
        fee, label = get_parent_fee_for_level(dl)
        self.assertEqual(fee, Decimal("35.00"))
        self.assertEqual(label, "Department default")
