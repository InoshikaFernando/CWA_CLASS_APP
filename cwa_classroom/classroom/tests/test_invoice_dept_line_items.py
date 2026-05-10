"""
Tests for department-scoped invoice line items and cascading account number
resolution (CPP-185).

Covers calculate_invoice_lines(department=...) across 5 account configurations
and 3 student-enrollment scenarios each.

School topology used throughout
────────────────────────────────
    school
    ├── dept_a
    │   ├── class_a1  (fee $10)
    │   └── class_a2  (fee $20)
    └── dept_b
        ├── class_b1  (fee $30)
        └── class_b2  (fee $40)

Three students — each enrolled in a different combination:
    student_single   → class_a1 only                       (1 class, 1 dept)
    student_samedept → class_a1 + class_a2                 (2 classes, same dept)
    student_multidept→ class_a1 + class_b1                 (2 classes, different depts)

Every class has exactly 1 completed session on SESSION_DATE with attendance
marked for all enrolled students, so every enrollment produces a billable line.

Account configurations (one test class per config)
───────────────────────────────────────────────────
  Config 1 — Only school has account
  Config 2 — Some departments have accounts (dept_a only)
  Config 3 — Some departments + some classes (dept_a + class_a2)
  Config 4 — All departments have accounts
  Config 5 — All departments + all classes have accounts
"""

import datetime
from decimal import Decimal

from django.test import TestCase

import classroom.invoicing_services as svc
from classroom.models import (
    ClassRoom, ClassSession, ClassStudent,
    Department, School, SchoolStudent, StudentAttendance,
)
from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERIOD_START = datetime.date(2025, 4, 1)
PERIOD_END   = datetime.date(2025, 4, 30)
SESSION_DATE = datetime.date(2025, 4, 7)  # within the billing period


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role(name):
    r, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return r


def _user(username):
    u = CustomUser.objects.create_user(
        username=username,
        password='password1!',
        email=f'wlhtestmails+{username}@gmail.com',
    )
    UserRole.objects.create(user=u, role=_role(Role.STUDENT))
    return u


def _lines(student, school, department=None):
    """Shorthand: call calculate_invoice_lines with the test period."""
    lines, _ = svc.calculate_invoice_lines(
        student, school,
        PERIOD_START, PERIOD_END,
        attendance_mode='all_class_days',
        billing_type='post_term',
        department=department,
    )
    return lines


def _classroom_ids(lines):
    return {li['classroom'].id for li in lines}


def _account(classroom):
    return classroom.get_resolved_account_number()


# ---------------------------------------------------------------------------
# Base test case — shared fixture
# ---------------------------------------------------------------------------

class _BaseLineItemTestCase(TestCase):
    """
    Creates the school topology once per test class.
    Subclasses override _configure_accounts() to set account numbers.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Owner & school ────────────────────────────────────────────────
        cls.owner = CustomUser.objects.create_user(
            username='dli_owner', password='password1!',
            email='wlhtestmails+dli_owner@gmail.com',
        )
        UserRole.objects.create(user=cls.owner, role=_role(Role.INSTITUTE_OWNER))
        cls.school = School.objects.create(
            name='DLI School', slug='dli-school',
            admin=cls.owner, is_active=True,
        )
        plan = InstitutePlan.objects.create(
            name='DLI Plan', slug='dli-plan',
            price=Decimal('0.00'),
            class_limit=50, student_limit=500,
            invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.00'),
        )
        SchoolSubscription.objects.create(
            school=cls.school, plan=plan, status='active'
        )

        # ── Departments ───────────────────────────────────────────────────
        cls.dept_a = Department.objects.create(
            school=cls.school, name='Dept A', slug='dli-dept-a',
        )
        cls.dept_b = Department.objects.create(
            school=cls.school, name='Dept B', slug='dli-dept-b',
        )

        # ── Classes ───────────────────────────────────────────────────────
        cls.class_a1 = ClassRoom.objects.create(
            name='Class A1', school=cls.school,
            department=cls.dept_a, fee_override=Decimal('10.00'),
        )
        cls.class_a2 = ClassRoom.objects.create(
            name='Class A2', school=cls.school,
            department=cls.dept_a, fee_override=Decimal('20.00'),
        )
        cls.class_b1 = ClassRoom.objects.create(
            name='Class B1', school=cls.school,
            department=cls.dept_b, fee_override=Decimal('30.00'),
        )
        cls.class_b2 = ClassRoom.objects.create(
            name='Class B2', school=cls.school,
            department=cls.dept_b, fee_override=Decimal('40.00'),
        )

        # ── Students ──────────────────────────────────────────────────────
        cls.student_single    = _user('dli_s_single')
        cls.student_samedept  = _user('dli_s_samedept')
        cls.student_multidept = _user('dli_s_multidept')

        for s in (cls.student_single, cls.student_samedept, cls.student_multidept):
            SchoolStudent.objects.create(school=cls.school, student=s)

        # student_single → class_a1 only
        ClassStudent.objects.create(
            classroom=cls.class_a1, student=cls.student_single, is_active=True
        )

        # student_samedept → class_a1 + class_a2 (same dept)
        ClassStudent.objects.create(
            classroom=cls.class_a1, student=cls.student_samedept, is_active=True
        )
        ClassStudent.objects.create(
            classroom=cls.class_a2, student=cls.student_samedept, is_active=True
        )

        # student_multidept → class_a1 + class_b1 (different depts)
        ClassStudent.objects.create(
            classroom=cls.class_a1, student=cls.student_multidept, is_active=True
        )
        ClassStudent.objects.create(
            classroom=cls.class_b1, student=cls.student_multidept, is_active=True
        )

        # ── Sessions ──────────────────────────────────────────────────────
        def _session(classroom):
            return ClassSession.objects.create(
                classroom=classroom,
                date=SESSION_DATE,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(10, 0),
                status='completed',
                created_by=cls.owner,
            )

        cls.sess_a1 = _session(cls.class_a1)
        cls.sess_a2 = _session(cls.class_a2)
        cls.sess_b1 = _session(cls.class_b1)
        cls.sess_b2 = _session(cls.class_b2)

        # ── Attendance ────────────────────────────────────────────────────
        # student_single → class_a1
        StudentAttendance.objects.create(
            session=cls.sess_a1, student=cls.student_single, status='present'
        )
        # student_samedept → class_a1 + class_a2
        StudentAttendance.objects.create(
            session=cls.sess_a1, student=cls.student_samedept, status='present'
        )
        StudentAttendance.objects.create(
            session=cls.sess_a2, student=cls.student_samedept, status='present'
        )
        # student_multidept → class_a1 + class_b1
        StudentAttendance.objects.create(
            session=cls.sess_a1, student=cls.student_multidept, status='present'
        )
        StudentAttendance.objects.create(
            session=cls.sess_b1, student=cls.student_multidept, status='present'
        )

    def _set_accounts(self, school=None, dept_a=None, dept_b=None,
                      class_a1=None, class_a2=None,
                      class_b1=None, class_b2=None):
        """Update account numbers on models and refresh from db."""
        fields = {
            self.school: ('bank_account_number', school),
            self.dept_a: ('bank_account_number', dept_a),
            self.dept_b: ('bank_account_number', dept_b),
            self.class_a1: ('bank_account_number', class_a1),
            self.class_a2: ('bank_account_number', class_a2),
            self.class_b1: ('bank_account_number', class_b1),
            self.class_b2: ('bank_account_number', class_b2),
        }
        for obj, (field, val) in fields.items():
            setattr(obj, field, val)
            obj.save(update_fields=[field])
            obj.refresh_from_db()
        # Also refresh related objects on classes so resolution picks up changes
        for cls_obj in (self.class_a1, self.class_a2, self.class_b1, self.class_b2):
            cls_obj.department.refresh_from_db()
            if cls_obj.school:
                cls_obj.school.refresh_from_db()


# ===========================================================================
# Config 1 — Only school has account number
# ===========================================================================

class Config1OnlySchoolAccountTests(_BaseLineItemTestCase):
    """
    school = 'SCHOOL-001'
    dept_a, dept_b, all classes = no override

    Expected resolved account for every class: 'SCHOOL-001'
    """

    def setUp(self):
        self._set_accounts(school='SCHOOL-001')

    # ── Scenario A: 1 student, 1 class, 1 dept ───────────────────────────

    def test_A_no_filter_returns_single_line(self):
        lines = _lines(self.student_single, self.school)
        self.assertEqual(len(lines), 1)
        self.assertIn(self.class_a1.id, _classroom_ids(lines))

    def test_A_dept_a_filter_returns_single_line(self):
        lines = _lines(self.student_single, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)
        self.assertIn(self.class_a1.id, _classroom_ids(lines))

    def test_A_dept_b_filter_returns_no_lines(self):
        lines = _lines(self.student_single, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    def test_A_resolved_account_is_school(self):
        self.class_a1.refresh_from_db()
        self.assertEqual(_account(self.class_a1), 'SCHOOL-001')

    # ── Scenario B: 1 student, 2 classes, same dept ───────────────────────

    def test_B_no_filter_returns_two_lines(self):
        lines = _lines(self.student_samedept, self.school)
        self.assertEqual(len(lines), 2)
        self.assertIn(self.class_a1.id, _classroom_ids(lines))
        self.assertIn(self.class_a2.id, _classroom_ids(lines))

    def test_B_dept_a_filter_returns_two_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 2)

    def test_B_dept_b_filter_returns_no_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    def test_B_both_classes_resolve_to_school_account(self):
        self.assertEqual(_account(self.class_a1), 'SCHOOL-001')
        self.assertEqual(_account(self.class_a2), 'SCHOOL-001')

    def test_B_correct_line_amounts(self):
        lines = _lines(self.student_samedept, self.school)
        amounts = {li['classroom'].id: li['line_amount'] for li in lines}
        self.assertEqual(amounts[self.class_a1.id], Decimal('10.00'))
        self.assertEqual(amounts[self.class_a2.id], Decimal('20.00'))

    # ── Scenario C: 1 student, 2 classes, different depts ────────────────

    def test_C_no_filter_returns_two_lines(self):
        lines = _lines(self.student_multidept, self.school)
        self.assertEqual(len(lines), 2)
        self.assertIn(self.class_a1.id, _classroom_ids(lines))
        self.assertIn(self.class_b1.id, _classroom_ids(lines))

    def test_C_dept_a_filter_returns_only_class_a1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_a1.id)

    def test_C_dept_b_filter_returns_only_class_b1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_b1.id)

    def test_C_both_classes_resolve_to_school_account(self):
        """Both depts have no override — both fall back to school account."""
        self.assertEqual(_account(self.class_a1), 'SCHOOL-001')
        self.assertEqual(_account(self.class_b1), 'SCHOOL-001')


# ===========================================================================
# Config 2 — Some departments have accounts (dept_a only)
# ===========================================================================

class Config2SomeDeptsHaveAccountTests(_BaseLineItemTestCase):
    """
    school = 'SCHOOL-001'
    dept_a = 'DEPT-A'
    dept_b, all classes = no override

    Expected resolved accounts:
        class_a1, class_a2 → 'DEPT-A'
        class_b1, class_b2 → 'SCHOOL-001' (dept_b has no override)
    """

    def setUp(self):
        self._set_accounts(school='SCHOOL-001', dept_a='DEPT-A')

    # ── Scenario A ────────────────────────────────────────────────────────

    def test_A_no_filter_returns_single_line(self):
        lines = _lines(self.student_single, self.school)
        self.assertEqual(len(lines), 1)

    def test_A_dept_a_filter_returns_single_line(self):
        lines = _lines(self.student_single, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)

    def test_A_dept_b_filter_returns_no_lines(self):
        lines = _lines(self.student_single, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    def test_A_class_a1_resolves_to_dept_a_account(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    # ── Scenario B ────────────────────────────────────────────────────────

    def test_B_no_filter_returns_two_lines(self):
        lines = _lines(self.student_samedept, self.school)
        self.assertEqual(len(lines), 2)

    def test_B_dept_a_filter_returns_two_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 2)

    def test_B_dept_b_filter_returns_no_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    def test_B_both_classes_in_dept_a_resolve_to_dept_a_account(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')
        self.assertEqual(_account(self.class_a2), 'DEPT-A')

    # ── Scenario C ────────────────────────────────────────────────────────

    def test_C_no_filter_returns_two_lines(self):
        lines = _lines(self.student_multidept, self.school)
        self.assertEqual(len(lines), 2)

    def test_C_dept_a_filter_returns_only_class_a1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_a1.id)

    def test_C_dept_b_filter_returns_only_class_b1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_b1.id)

    def test_C_dept_a_class_resolves_to_dept_a_account(self):
        """class_a1 is in dept_a which has override → DEPT-A."""
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    def test_C_dept_b_class_falls_back_to_school_account(self):
        """class_b1 is in dept_b which has no override → falls back to school."""
        self.assertEqual(_account(self.class_b1), 'SCHOOL-001')

    def test_C_two_different_resolved_accounts(self):
        """Multi-dept invoice has two distinct resolved account numbers."""
        self.assertNotEqual(_account(self.class_a1), _account(self.class_b1))


# ===========================================================================
# Config 3 — Some departments + some classes have accounts
# ===========================================================================

class Config3SomeDeptsAndClassesHaveAccountTests(_BaseLineItemTestCase):
    """
    school = 'SCHOOL-001'
    dept_a = 'DEPT-A'
    class_a2 = 'CLASS-A2'   ← class override wins over dept override
    dept_b, class_a1, class_b1, class_b2 = no override

    Expected resolved accounts:
        class_a1 → 'DEPT-A'        (dept override; no class override)
        class_a2 → 'CLASS-A2'      (class override wins)
        class_b1 → 'SCHOOL-001'    (no dept/class override)
        class_b2 → 'SCHOOL-001'
    """

    def setUp(self):
        self._set_accounts(
            school='SCHOOL-001',
            dept_a='DEPT-A',
            class_a2='CLASS-A2',
        )

    # ── Scenario A ────────────────────────────────────────────────────────

    def test_A_class_a1_resolves_to_dept_a(self):
        """No class override → falls back to dept_a override."""
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    def test_A_dept_a_filter_one_line(self):
        lines = _lines(self.student_single, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)

    def test_A_dept_b_filter_zero_lines(self):
        lines = _lines(self.student_single, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    # ── Scenario B ────────────────────────────────────────────────────────

    def test_B_class_a1_resolves_to_dept_a(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    def test_B_class_a2_class_override_wins_over_dept(self):
        """class_a2 has its own override — it should win over dept_a's value."""
        self.assertEqual(_account(self.class_a2), 'CLASS-A2')

    def test_B_dept_a_filter_returns_both_classes(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 2)
        self.assertIn(self.class_a1.id, _classroom_ids(lines))
        self.assertIn(self.class_a2.id, _classroom_ids(lines))

    def test_B_two_classes_same_dept_different_accounts(self):
        """class_a1 uses dept account, class_a2 uses its own — should differ."""
        self.assertNotEqual(_account(self.class_a1), _account(self.class_a2))

    # ── Scenario C ────────────────────────────────────────────────────────

    def test_C_dept_a_filter_returns_only_class_a1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_a1.id)

    def test_C_dept_b_filter_returns_only_class_b1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_b1.id)

    def test_C_class_a1_resolves_to_dept_a(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    def test_C_class_b1_falls_back_to_school(self):
        self.assertEqual(_account(self.class_b1), 'SCHOOL-001')


# ===========================================================================
# Config 4 — All departments have accounts
# ===========================================================================

class Config4AllDeptsHaveAccountTests(_BaseLineItemTestCase):
    """
    school = 'SCHOOL-001'
    dept_a = 'DEPT-A'
    dept_b = 'DEPT-B'
    all classes = no override

    Expected resolved accounts:
        class_a1, class_a2 → 'DEPT-A'
        class_b1, class_b2 → 'DEPT-B'
    """

    def setUp(self):
        self._set_accounts(
            school='SCHOOL-001',
            dept_a='DEPT-A',
            dept_b='DEPT-B',
        )

    # ── Scenario A ────────────────────────────────────────────────────────

    def test_A_class_a1_resolves_to_dept_a(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    def test_A_dept_a_filter_one_line(self):
        lines = _lines(self.student_single, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)

    def test_A_dept_b_filter_zero_lines(self):
        lines = _lines(self.student_single, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    # ── Scenario B ────────────────────────────────────────────────────────

    def test_B_both_dept_a_classes_resolve_to_dept_a(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')
        self.assertEqual(_account(self.class_a2), 'DEPT-A')

    def test_B_dept_a_filter_returns_both_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 2)

    def test_B_dept_b_filter_zero_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    def test_B_no_filter_two_lines(self):
        lines = _lines(self.student_samedept, self.school)
        self.assertEqual(len(lines), 2)

    # ── Scenario C ────────────────────────────────────────────────────────

    def test_C_no_filter_two_lines(self):
        lines = _lines(self.student_multidept, self.school)
        self.assertEqual(len(lines), 2)

    def test_C_dept_a_filter_returns_only_class_a1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_a1.id)

    def test_C_dept_b_filter_returns_only_class_b1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_b1.id)

    def test_C_class_a1_resolves_to_dept_a(self):
        self.assertEqual(_account(self.class_a1), 'DEPT-A')

    def test_C_class_b1_resolves_to_dept_b(self):
        self.assertEqual(_account(self.class_b1), 'DEPT-B')

    def test_C_school_account_not_used_when_all_depts_have_overrides(self):
        """School fallback should NOT be used when every dept has its own account."""
        self.assertNotEqual(_account(self.class_a1), 'SCHOOL-001')
        self.assertNotEqual(_account(self.class_b1), 'SCHOOL-001')

    def test_C_two_distinct_accounts_for_multi_dept_student(self):
        """Multi-dept invoice should result in two different account numbers."""
        self.assertNotEqual(_account(self.class_a1), _account(self.class_b1))


# ===========================================================================
# Config 5 — All departments + all classes have accounts
# ===========================================================================

class Config5AllDeptsAndClassesHaveAccountTests(_BaseLineItemTestCase):
    """
    school = 'SCHOOL-001'
    dept_a = 'DEPT-A'
    dept_b = 'DEPT-B'
    class_a1 = 'CLASS-A1'
    class_a2 = 'CLASS-A2'
    class_b1 = 'CLASS-B1'
    class_b2 = 'CLASS-B2'

    Resolution: class override ALWAYS wins.
    Expected resolved accounts:
        class_a1 → 'CLASS-A1'
        class_a2 → 'CLASS-A2'
        class_b1 → 'CLASS-B1'
        class_b2 → 'CLASS-B2'
    """

    def setUp(self):
        self._set_accounts(
            school='SCHOOL-001',
            dept_a='DEPT-A',
            dept_b='DEPT-B',
            class_a1='CLASS-A1',
            class_a2='CLASS-A2',
            class_b1='CLASS-B1',
            class_b2='CLASS-B2',
        )

    # ── Scenario A ────────────────────────────────────────────────────────

    def test_A_class_override_wins_over_dept_and_school(self):
        self.assertEqual(_account(self.class_a1), 'CLASS-A1')

    def test_A_dept_a_filter_one_line(self):
        lines = _lines(self.student_single, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)

    def test_A_dept_b_filter_zero_lines(self):
        lines = _lines(self.student_single, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    # ── Scenario B ────────────────────────────────────────────────────────

    def test_B_class_a1_uses_own_account(self):
        self.assertEqual(_account(self.class_a1), 'CLASS-A1')

    def test_B_class_a2_uses_own_account(self):
        self.assertEqual(_account(self.class_a2), 'CLASS-A2')

    def test_B_two_classes_same_dept_different_class_accounts(self):
        """Each class has its own override — accounts must differ even within same dept."""
        self.assertNotEqual(_account(self.class_a1), _account(self.class_a2))

    def test_B_dept_a_filter_returns_both_classes(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 2)

    def test_B_dept_b_filter_returns_no_lines(self):
        lines = _lines(self.student_samedept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 0)

    def test_B_class_accounts_not_dept_accounts(self):
        """class_a1 and class_a2 both belong to dept_a, but should NOT resolve to DEPT-A."""
        self.assertNotEqual(_account(self.class_a1), 'DEPT-A')
        self.assertNotEqual(_account(self.class_a2), 'DEPT-A')

    # ── Scenario C ────────────────────────────────────────────────────────

    def test_C_no_filter_two_lines(self):
        lines = _lines(self.student_multidept, self.school)
        self.assertEqual(len(lines), 2)

    def test_C_dept_a_filter_returns_only_class_a1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_a)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_a1.id)

    def test_C_dept_b_filter_returns_only_class_b1(self):
        lines = _lines(self.student_multidept, self.school, department=self.dept_b)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['classroom'].id, self.class_b1.id)

    def test_C_class_a1_uses_own_account_not_dept_or_school(self):
        self.assertEqual(_account(self.class_a1), 'CLASS-A1')
        self.assertNotEqual(_account(self.class_a1), 'DEPT-A')
        self.assertNotEqual(_account(self.class_a1), 'SCHOOL-001')

    def test_C_class_b1_uses_own_account_not_dept_or_school(self):
        self.assertEqual(_account(self.class_b1), 'CLASS-B1')
        self.assertNotEqual(_account(self.class_b1), 'DEPT-B')
        self.assertNotEqual(_account(self.class_b1), 'SCHOOL-001')

    def test_C_four_unique_accounts_across_all_classes(self):
        """Every class has a distinct account — 4 unique values expected."""
        accounts = {
            _account(self.class_a1),
            _account(self.class_a2),
            _account(self.class_b1),
            _account(self.class_b2),
        }
        self.assertEqual(len(accounts), 4)
