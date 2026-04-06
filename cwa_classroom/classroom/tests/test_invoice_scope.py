"""
Tests for the cascading invoice scope filter (Department → Class → Students)
introduced in GenerateInvoicesView.

Covers:
  1. HTMX API — classes cascade by department
  2. HTMX API — students cascade by classroom
  3. Invoice generation — entire school
  4. Invoice generation — filter by department
  5. Invoice generation — filter by class
  6. Invoice generation — single student
  7. Invoice generation — multiple students (explicit list)
  8. Scope + overlap: new students alongside already-invoiced students
  9. Scope + draft replacement: draft invoice replaced when scope targets that student
 10. Scope + gap invoice: partial issued invoice → supplementary for remaining sessions
"""
import datetime
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    ClassRoom, ClassSession, ClassStudent, Department,
    DepartmentSubject, Invoice, InvoiceLineItem,
    School, SchoolStudent, StudentAttendance,
    Subject,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

PERIOD_START = datetime.date(2025, 3, 1)
PERIOD_END   = datetime.date(2025, 3, 31)

POST_DATA_BASE = {
    'billing_period_start': str(PERIOD_START),
    'billing_period_end':   str(PERIOD_END),
    'attendance_mode':      'all_class_days',
    'billing_type':         'post_term',
    'period_type':          'custom',
}


def _role(name):
    r, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return r


def _user(username, role_name, **kw):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234',
        email=f'{username}@test.local', **kw
    )
    UserRole.objects.create(user=u, role=_role(role_name))
    return u


class InvoiceScopeTestCase(TestCase):
    """
    School topology:
        dept_a  ─── class_a  (fee $10/session)
                        student_a  (enrolled)
                        student_c  (enrolled, "new" — no prior invoice)
        dept_b  ─── class_b  (fee $15/session)
                        student_b  (enrolled)

    Each class has one completed session on 2025-03-10 with attendance
    marked for every enrolled student, so attendance validation passes.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Owner / school ────────────────────────────────────────────────
        cls.owner = _user('inv_owner', Role.INSTITUTE_OWNER)
        cls.school = School.objects.create(
            name='Scope School', slug='scope-school', admin=cls.owner,
            is_active=True,
        )
        plan = InstitutePlan.objects.create(
            name='Scope Plan', slug='scope-plan', price=Decimal('89.00'),
            stripe_price_id='price_scope', class_limit=50, student_limit=500,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )
        SchoolSubscription.objects.create(school=cls.school, plan=plan, status='active')
        # owner is school.admin → found by _get_user_school_ids via admin=user filter
        # No SchoolTeacher record needed for the owner

        # ── Subject ───────────────────────────────────────────────────────
        cls.subject, _ = Subject.objects.get_or_create(
            slug='maths-scope',
            defaults={'name': 'Maths Scope', 'is_active': True},
        )

        # ── Departments ───────────────────────────────────────────────────
        cls.dept_a = Department.objects.create(
            school=cls.school, name='Dept A', slug='dept-a-scope',
        )
        cls.dept_b = Department.objects.create(
            school=cls.school, name='Dept B', slug='dept-b-scope',
        )
        DepartmentSubject.objects.create(department=cls.dept_a, subject=cls.subject)
        DepartmentSubject.objects.create(department=cls.dept_b, subject=cls.subject)

        # ── Classes (with fee override so calculate_invoice_lines returns lines) ─
        cls.class_a = ClassRoom.objects.create(
            name='Class A', school=cls.school,
            department=cls.dept_a, subject=cls.subject,
            fee_override=Decimal('10.00'),
        )
        cls.class_b = ClassRoom.objects.create(
            name='Class B', school=cls.school,
            department=cls.dept_b, subject=cls.subject,
            fee_override=Decimal('15.00'),
        )

        # ── Students ──────────────────────────────────────────────────────
        cls.student_a = _user('student_a_scope', Role.STUDENT, first_name='Alice', last_name='A')
        cls.student_b = _user('student_b_scope', Role.STUDENT, first_name='Bob',   last_name='B')
        cls.student_c = _user('student_c_scope', Role.STUDENT, first_name='Carol', last_name='C')

        for s in (cls.student_a, cls.student_b, cls.student_c):
            SchoolStudent.objects.create(school=cls.school, student=s)

        # student_a + student_c → class_a
        ClassStudent.objects.create(classroom=cls.class_a, student=cls.student_a, is_active=True)
        ClassStudent.objects.create(classroom=cls.class_a, student=cls.student_c, is_active=True)
        # student_b → class_b
        ClassStudent.objects.create(classroom=cls.class_b, student=cls.student_b, is_active=True)

        # ── Completed sessions + attendance (so attendance validation passes) ─
        session_date = datetime.date(2025, 3, 10)

        cls.session_a = ClassSession.objects.create(
            classroom=cls.class_a, date=session_date,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='completed', created_by=cls.owner,
        )
        cls.session_b = ClassSession.objects.create(
            classroom=cls.class_b, date=session_date,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='completed', created_by=cls.owner,
        )

        # Mark ALL enrolled students present so validate_attendance_complete passes
        for student in (cls.student_a, cls.student_c):
            StudentAttendance.objects.create(
                session=cls.session_a, student=student, status='present',
            )
        StudentAttendance.objects.create(
            session=cls.session_b, student=cls.student_b, status='present',
        )

    def _client(self):
        c = Client()
        c.login(username='inv_owner', password='pass1234')
        return c

    def _post(self, client, extra=None):
        data = {**POST_DATA_BASE, **(extra or {})}
        return client.post(reverse('generate_invoices'), data, follow=True)

    def _draft_ids_from_session(self, client):
        return client.session.get('draft_invoice_ids', [])

    def _make_invoice(self, student, status='issued',
                      start=None, end=None, amount='50.00'):
        return Invoice.objects.create(
            invoice_number=f'INV-SCOPE-{Invoice.objects.count() + 1:04d}',
            school=self.school,
            student=student,
            billing_period_start=start or PERIOD_START,
            billing_period_end=end or PERIOD_END,
            attendance_mode='all_class_days',
            calculated_amount=Decimal(amount),
            amount=Decimal(amount),
            status=status,
            created_by=self.owner,
        )


# ===========================================================================
# 1. HTMX API — class cascade
# ===========================================================================

class InvoicingScopeClassAPITests(InvoiceScopeTestCase):

    def test_scope_classes_no_dept_returns_all_classes(self):
        """No department filter → all active classes returned."""
        c = self._client()
        resp = c.get(reverse('invoicing_scope_classes'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Class A', content)
        self.assertIn('Class B', content)

    def test_scope_classes_filtered_by_dept_a(self):
        c = self._client()
        resp = c.get(reverse('invoicing_scope_classes'), {'department_id': self.dept_a.id})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Class A', content)
        self.assertNotIn('Class B', content)

    def test_scope_classes_filtered_by_dept_b(self):
        c = self._client()
        resp = c.get(reverse('invoicing_scope_classes'), {'department_id': self.dept_b.id})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Class A', content)
        self.assertIn('Class B', content)

    def test_scope_classes_requires_login(self):
        resp = Client().get(reverse('invoicing_scope_classes'))
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# 2. HTMX API — student cascade
# ===========================================================================

class InvoicingScopeStudentAPITests(InvoiceScopeTestCase):

    def test_scope_students_no_class_returns_all(self):
        """No classroom filter → all school students returned."""
        c = self._client()
        resp = c.get(reverse('invoicing_scope_students'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Alice', content)
        self.assertIn('Bob', content)
        self.assertIn('Carol', content)

    def test_scope_students_filtered_by_class_a(self):
        c = self._client()
        resp = c.get(reverse('invoicing_scope_students'), {'classroom_id': self.class_a.id})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Alice', content)
        self.assertIn('Carol', content)
        self.assertNotIn('Bob', content)

    def test_scope_students_filtered_by_class_b(self):
        c = self._client()
        resp = c.get(reverse('invoicing_scope_students'), {'classroom_id': self.class_b.id})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Alice', content)
        self.assertNotIn('Carol', content)
        self.assertIn('Bob', content)

    def test_scope_students_requires_login(self):
        resp = Client().get(reverse('invoicing_scope_students'))
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# 3. Invoice generation — entire school (no scope filter)
# ===========================================================================

class GenerateInvoicesEntireSchoolTests(InvoiceScopeTestCase):

    def test_entire_school_generates_for_all_students(self):
        """No dept/class/student filter → all 3 students get draft invoices."""
        c = self._client()
        resp = self._post(c)
        self.assertEqual(resp.status_code, 200)

        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 3)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_b.id, invoiced_students)
        self.assertIn(self.student_c.id, invoiced_students)

    def test_entire_school_correct_amounts(self):
        """Class A fee $10 × 1 session = $10; Class B fee $15 × 1 session = $15."""
        c = self._client()
        self._post(c)
        draft_ids = self._draft_ids_from_session(c)

        inv_a = Invoice.objects.get(id__in=draft_ids, student=self.student_a)
        inv_b = Invoice.objects.get(id__in=draft_ids, student=self.student_b)
        inv_c = Invoice.objects.get(id__in=draft_ids, student=self.student_c)

        self.assertEqual(inv_a.amount, Decimal('10.00'))
        self.assertEqual(inv_b.amount, Decimal('15.00'))
        self.assertEqual(inv_c.amount, Decimal('10.00'))


# ===========================================================================
# 4. Invoice generation — filter by department
# ===========================================================================

class GenerateInvoicesByDepartmentTests(InvoiceScopeTestCase):

    def test_dept_a_only_invoices_class_a_students(self):
        c = self._client()
        self._post(c, {'department_id': self.dept_a.id})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 2)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_c.id, invoiced_students)
        self.assertNotIn(self.student_b.id, invoiced_students)

    def test_dept_b_only_invoices_class_b_students(self):
        c = self._client()
        self._post(c, {'department_id': self.dept_b.id})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 1)

        inv = Invoice.objects.get(id__in=draft_ids)
        self.assertEqual(inv.student_id, self.student_b.id)

    def test_dept_filter_does_not_affect_other_dept(self):
        """student_b (dept_b) must NOT appear when filtering by dept_a."""
        c = self._client()
        self._post(c, {'department_id': self.dept_a.id})
        draft_ids = self._draft_ids_from_session(c)
        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertNotIn(self.student_b.id, invoiced_students)


# ===========================================================================
# 5. Invoice generation — filter by class
# ===========================================================================

class GenerateInvoicesByClassTests(InvoiceScopeTestCase):

    def test_class_a_filter_invoices_only_class_a_students(self):
        c = self._client()
        self._post(c, {'classroom_id': self.class_a.id})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 2)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_c.id, invoiced_students)
        self.assertNotIn(self.student_b.id, invoiced_students)

    def test_class_b_filter_invoices_only_class_b_students(self):
        c = self._client()
        self._post(c, {'classroom_id': self.class_b.id})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 1)

        inv = Invoice.objects.get(id__in=draft_ids)
        self.assertEqual(inv.student_id, self.student_b.id)

    def test_class_filter_generates_correct_line_items(self):
        """Line items must belong to the filtered class only."""
        c = self._client()
        self._post(c, {'classroom_id': self.class_b.id})
        draft_ids = self._draft_ids_from_session(c)

        inv = Invoice.objects.get(id__in=draft_ids)
        line_classrooms = set(
            InvoiceLineItem.objects.filter(invoice=inv)
            .values_list('classroom_id', flat=True)
        )
        self.assertEqual(line_classrooms, {self.class_b.id})


# ===========================================================================
# 6. Invoice generation — single student
# ===========================================================================

class GenerateInvoicesSingleStudentTests(InvoiceScopeTestCase):

    def test_single_student_selection(self):
        c = self._client()
        self._post(c, {'student_ids': [self.student_a.id]})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 1)
        inv = Invoice.objects.get(id__in=draft_ids)
        self.assertEqual(inv.student_id, self.student_a.id)

    def test_single_student_excludes_others(self):
        c = self._client()
        self._post(c, {'student_ids': [self.student_b.id]})
        draft_ids = self._draft_ids_from_session(c)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertNotIn(self.student_a.id, invoiced_students)
        self.assertNotIn(self.student_c.id, invoiced_students)
        self.assertIn(self.student_b.id, invoiced_students)

    def test_single_student_with_class_scope_respected(self):
        """student_ids takes priority over classroom_id."""
        c = self._client()
        self._post(c, {
            'classroom_id': self.class_a.id,
            'student_ids':  [self.student_a.id],
        })
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 1)
        self.assertEqual(Invoice.objects.get(id__in=draft_ids).student_id, self.student_a.id)


# ===========================================================================
# 7. Invoice generation — multiple explicit students
# ===========================================================================

class GenerateInvoicesMultipleStudentsTests(InvoiceScopeTestCase):

    def test_two_students_from_same_class(self):
        c = self._client()
        self._post(c, {'student_ids': [self.student_a.id, self.student_c.id]})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 2)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_c.id, invoiced_students)
        self.assertNotIn(self.student_b.id, invoiced_students)

    def test_two_students_from_different_classes(self):
        c = self._client()
        self._post(c, {'student_ids': [self.student_a.id, self.student_b.id]})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 2)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_b.id, invoiced_students)
        self.assertNotIn(self.student_c.id, invoiced_students)

    def test_all_three_students_explicit_list(self):
        c = self._client()
        self._post(c, {
            'student_ids': [self.student_a.id, self.student_b.id, self.student_c.id],
        })
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 3)


# ===========================================================================
# 8. Mixed: some already invoiced, some new — class scope
# ===========================================================================

class GenerateInvoicesMixedScopeTests(InvoiceScopeTestCase):

    def test_class_scope_new_student_invoiced_when_others_fully_covered(self):
        """
        student_a already has a fully-covering issued invoice.
        student_c has no invoice.
        Filter by class_a → student_c gets a new invoice; student_a is skipped.
        """
        self._make_invoice(self.student_a, status='issued')

        c = self._client()
        self._post(c, {'classroom_id': self.class_a.id})
        draft_ids = self._draft_ids_from_session(c)

        # Only student_c should get a draft
        self.assertEqual(len(draft_ids), 1)
        inv = Invoice.objects.get(id__in=draft_ids)
        self.assertEqual(inv.student_id, self.student_c.id)

    def test_school_scope_skips_fully_covered_keeps_others(self):
        """
        student_b has a fully-covering issued invoice.
        student_a and student_c have none.
        Entire school → 2 drafts (a and c), student_b skipped.
        """
        self._make_invoice(self.student_b, status='issued')

        c = self._client()
        self._post(c)
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 2)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_c.id, invoiced_students)
        self.assertNotIn(self.student_b.id, invoiced_students)


# ===========================================================================
# 9. Draft replacement within scope
# ===========================================================================

class GenerateInvoicesDraftReplacementScopeTests(InvoiceScopeTestCase):

    def test_class_scope_replaces_draft_for_targeted_student(self):
        """
        student_a has a draft invoice for the same period.
        Filter by class_a (includes student_a and student_c).
        → draft cancelled + fresh draft for student_a; new draft for student_c.
        """
        draft_inv = self._make_invoice(self.student_a, status='draft')

        c = self._client()
        self._post(c, {'classroom_id': self.class_a.id})

        # Original draft must now be cancelled
        draft_inv.refresh_from_db()
        self.assertEqual(draft_inv.status, 'cancelled')

        # 2 new drafts (student_a replaced, student_c new)
        new_draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(new_draft_ids), 2)
        self.assertNotIn(draft_inv.id, new_draft_ids)

    def test_single_student_scope_replaces_only_their_draft(self):
        """
        student_a has a draft; student_c has none.
        Select only student_a → student_a draft replaced; student_c untouched.
        """
        draft_a = self._make_invoice(self.student_a, status='draft')

        c = self._client()
        self._post(c, {'student_ids': [self.student_a.id]})

        draft_a.refresh_from_db()
        self.assertEqual(draft_a.status, 'cancelled')

        new_draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(new_draft_ids), 1)
        inv = Invoice.objects.get(id__in=new_draft_ids)
        self.assertEqual(inv.student_id, self.student_a.id)

        # student_c must still have no invoice
        self.assertFalse(
            Invoice.objects.filter(student=self.student_c).exclude(status='cancelled').exists()
        )


# ===========================================================================
# 10. Gap (supplementary) invoice within scope
# ===========================================================================

class GenerateInvoicesGapScopeTests(InvoiceScopeTestCase):
    """
    student_a has an issued invoice covering Mar 1–10 only.
    The requested period is Mar 1–31.
    Session on Mar 10 is already in the issued period; any sessions after Mar 10
    would be the "gap". Since our test only has one session on Mar 10, there
    are no uncovered sessions — so student_a is skipped (no sessions in gap).

    To test an actual gap invoice we add a second session on Mar 24 (after the
    issued invoice ends on Mar 10).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Second session on Mar 24 for class_a (after the partial invoice ends)
        cls.session_a2 = ClassSession.objects.create(
            classroom=cls.class_a,
            date=datetime.date(2025, 3, 24),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='completed',
            created_by=cls.owner,
        )
        # Attendance for both class_a students on the second session
        for student in (cls.student_a, cls.student_c):
            StudentAttendance.objects.create(
                session=cls.session_a2, student=student, status='present',
            )

    def test_gap_invoice_generated_for_uncovered_sessions(self):
        """
        student_a: issued invoice Mar 1–10. Period requested: Mar 1–31.
        Uncovered: Mar 11–31, which contains session_a2 (Mar 24).
        → Supplementary invoice generated for student_a covering session_a2.
        student_c: no prior invoice → normal invoice for both sessions.
        """
        self._make_invoice(
            self.student_a, status='issued',
            start=datetime.date(2025, 3, 1),
            end=datetime.date(2025, 3, 10),
        )

        c = self._client()
        self._post(c, {'classroom_id': self.class_a.id})
        draft_ids = self._draft_ids_from_session(c)

        # Both student_a (gap) and student_c (full) must get drafts
        self.assertEqual(len(draft_ids), 2)

        invoiced_students = set(
            Invoice.objects.filter(id__in=draft_ids)
            .values_list('student_id', flat=True)
        )
        self.assertIn(self.student_a.id, invoiced_students)
        self.assertIn(self.student_c.id, invoiced_students)

    def test_gap_invoice_covers_only_uncovered_sessions(self):
        """
        student_a's gap invoice should charge for 1 session (Mar 24 only),
        not the Mar 10 session already covered by the issued invoice.
        """
        self._make_invoice(
            self.student_a, status='issued',
            start=datetime.date(2025, 3, 1),
            end=datetime.date(2025, 3, 10),
        )

        c = self._client()
        self._post(c, {'student_ids': [self.student_a.id]})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 1)

        gap_inv = Invoice.objects.get(id__in=draft_ids)
        self.assertEqual(gap_inv.student_id, self.student_a.id)

        # The gap invoice should bill for exactly 1 session (Mar 24)
        line = InvoiceLineItem.objects.get(invoice=gap_inv)
        self.assertEqual(line.sessions_charged, 1)
        self.assertEqual(gap_inv.amount, Decimal('10.00'))  # 1 session × $10

    def test_fully_covered_student_skipped_within_scope(self):
        """
        student_a has issued invoice covering the full period Mar 1–31.
        Selecting student_a explicitly → skipped, no draft created.
        """
        self._make_invoice(
            self.student_a, status='issued',
            start=PERIOD_START, end=PERIOD_END,
        )

        c = self._client()
        self._post(c, {'student_ids': [self.student_a.id]})
        draft_ids = self._draft_ids_from_session(c)
        self.assertEqual(len(draft_ids), 0)
