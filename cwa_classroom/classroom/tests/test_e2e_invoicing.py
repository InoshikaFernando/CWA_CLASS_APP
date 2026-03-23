"""
End-to-end tests for the invoicing system and parent portal.

Covers: invoice generation, fee management, payment recording,
parent portal views, and invoice notifications.
"""

import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject,
    Subject, Level, ClassRoom, ClassTeacher, ClassStudent,
    SchoolStudent,
    Invoice, InvoiceLineItem, InvoicePayment,
    DepartmentFee, StudentFeeOverride,
    ProgressCriteria, ProgressRecord,
    Notification, ParentStudent, CreditTransaction,
)
from attendance.models import ClassSession, StudentAttendance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name, display_name=None):
    """Helper: get-or-create a Role row."""
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='testpass123', **kwargs):
    """Helper: create a CustomUser."""
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'{username}@example.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    """Helper: assign a role to a user."""
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school_with_subscription(admin_user, school_name='Test School'):
    """Create a school with an active subscription so middleware passes."""
    school = School.objects.create(
        name=school_name,
        slug=school_name.lower().replace(' ', '-'),
        admin=admin_user,
        is_active=True,
        invoice_due_days=30,
    )
    plan = InstitutePlan.objects.create(
        name='Test Plan',
        slug='test-plan',
        price=Decimal('0.00'),
        class_limit=100,
        student_limit=100,
        invoice_limit_yearly=1000,
        extra_invoice_rate=Decimal('0.00'),
    )
    SchoolSubscription.objects.create(
        school=school,
        plan=plan,
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    return school


def _create_classroom(school, department, subject, name='Test Class'):
    """Create a classroom in the given school/department."""
    classroom = ClassRoom(
        name=name,
        school=school,
        department=department,
        subject=subject,
    )
    classroom.save()
    return classroom


def _create_completed_session(classroom, date, teacher, start_time=None, end_time=None):
    """Create a completed session with default times."""
    return ClassSession.objects.create(
        classroom=classroom,
        date=date,
        start_time=start_time or datetime.time(9, 0),
        end_time=end_time or datetime.time(10, 0),
        status='completed',
        created_by=teacher,
    )


def _mark_attendance(session, student, status='present', marked_by=None):
    """Mark a student's attendance for a session."""
    return StudentAttendance.objects.create(
        session=session,
        student=student,
        status=status,
        marked_by=marked_by or student,
    )


# ---------------------------------------------------------------------------
# 1. InvoiceCreationTest
# ---------------------------------------------------------------------------

class InvoiceCreationTest(TestCase):
    """Test the full invoice generation and lifecycle workflow."""

    @classmethod
    def setUpTestData(cls):
        # Admin user
        cls.admin = _create_user('admin_inv', first_name='Admin', last_name='Inv')
        _assign_role(cls.admin, Role.ADMIN)
        _assign_role(cls.admin, Role.HEAD_OF_INSTITUTE)

        # School with subscription
        cls.school = _setup_school_with_subscription(cls.admin)

        # Teacher
        cls.teacher = _create_user('teacher_inv', first_name='Teacher', last_name='One')
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        # Department, subject, level
        cls.subject = Subject.objects.create(name='Maths', slug='maths', school=cls.school)
        cls.department = Department.objects.create(
            school=cls.school, name='Mathematics', slug='mathematics',
            default_fee=Decimal('25.00'),
        )
        DepartmentSubject.objects.create(department=cls.department, subject=cls.subject)

        # Classroom
        cls.classroom = _create_classroom(
            cls.school, cls.department, cls.subject, name='Year 3 Maths',
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        # Students
        cls.student1 = _create_user('student_inv1', first_name='Alice', last_name='Smith')
        _assign_role(cls.student1, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student1)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student1, is_active=True,
        )

        cls.student2 = _create_user('student_inv2', first_name='Bob', last_name='Jones')
        _assign_role(cls.student2, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student2)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student2, is_active=True,
        )

        # Billing period
        cls.period_start = datetime.date(2026, 3, 1)
        cls.period_end = datetime.date(2026, 3, 15)

        # Create completed sessions with attendance for both students
        for day_offset in (1, 4, 8, 11):
            session_date = datetime.date(2026, 3, day_offset)
            session = _create_completed_session(cls.classroom, session_date, cls.teacher)
            _mark_attendance(session, cls.student1, 'present', cls.teacher)
            _mark_attendance(session, cls.student2, 'present', cls.teacher)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_generate_draft_invoices(self):
        """POST to generate_invoices creates draft invoices for enrolled students."""
        url = reverse('generate_invoices')
        data = {
            'billing_period_start': '2026-03-01',
            'billing_period_end': '2026-03-15',
            'attendance_mode': 'all_class_days',
        }
        response = self.client.post(url, data)

        # Should redirect to preview page
        self.assertEqual(response.status_code, 302)
        self.assertIn('preview', response.url)

        # Drafts should exist for both students
        drafts = Invoice.objects.filter(school=self.school, status='draft')
        self.assertEqual(drafts.count(), 2)

        for inv in drafts:
            self.assertEqual(inv.billing_period_start, self.period_start)
            self.assertEqual(inv.billing_period_end, self.period_end)
            self.assertEqual(inv.attendance_mode, 'all_class_days')

    def test_draft_invoice_has_correct_line_items(self):
        """Generated draft invoices have line items reflecting sessions and rates."""
        url = reverse('generate_invoices')
        self.client.post(url, {
            'billing_period_start': '2026-03-01',
            'billing_period_end': '2026-03-15',
            'attendance_mode': 'all_class_days',
        })

        invoice = Invoice.objects.filter(
            school=self.school, student=self.student1, status='draft',
        ).first()
        self.assertIsNotNone(invoice)

        line_items = invoice.line_items.all()
        self.assertGreaterEqual(line_items.count(), 1)

        class_line = line_items.filter(classroom=self.classroom).first()
        self.assertIsNotNone(class_line)
        # 4 completed sessions, department default_fee = 25.00
        self.assertEqual(class_line.sessions_held, 4)
        self.assertEqual(class_line.sessions_charged, 4)
        self.assertEqual(class_line.daily_rate, Decimal('25.00'))
        self.assertEqual(class_line.line_amount, Decimal('100.00'))
        self.assertEqual(invoice.amount, Decimal('100.00'))

    def test_issue_invoices_changes_status_to_issued(self):
        """Issuing draft invoices sets status=issued and populates issued_at/due_date."""
        # Generate drafts first
        self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '2026-03-01',
            'billing_period_end': '2026-03-15',
            'attendance_mode': 'all_class_days',
        })

        draft_ids = list(
            Invoice.objects.filter(school=self.school, status='draft')
            .values_list('id', flat=True)
        )
        self.assertTrue(len(draft_ids) > 0)

        # Store in session for the issue view
        session = self.client.session
        session['draft_invoice_ids'] = draft_ids
        session.save()

        response = self.client.post(reverse('issue_invoices'))
        self.assertEqual(response.status_code, 302)

        for inv in Invoice.objects.filter(id__in=draft_ids):
            self.assertEqual(inv.status, 'issued')
            self.assertIsNotNone(inv.issued_at)
            self.assertIsNotNone(inv.due_date)

    def test_cancel_invoice(self):
        """Cancelling an issued invoice sets status=cancelled with reason."""
        # Generate and issue
        self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '2026-03-01',
            'billing_period_end': '2026-03-15',
            'attendance_mode': 'all_class_days',
        })

        draft_ids = list(
            Invoice.objects.filter(school=self.school, status='draft')
            .values_list('id', flat=True)
        )
        session = self.client.session
        session['draft_invoice_ids'] = draft_ids
        session.save()
        self.client.post(reverse('issue_invoices'))

        invoice = Invoice.objects.filter(school=self.school, status='issued').first()
        self.assertIsNotNone(invoice)

        url = reverse('cancel_invoice', kwargs={'invoice_id': invoice.id})
        response = self.client.post(url, {
            'cancellation_reason': 'Billing error',
        })
        self.assertEqual(response.status_code, 302)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'cancelled')
        self.assertEqual(invoice.cancellation_reason, 'Billing error')
        self.assertIsNotNone(invoice.cancelled_at)


# ---------------------------------------------------------------------------
# 2. FeeManagementTest
# ---------------------------------------------------------------------------

class FeeManagementTest(TestCase):
    """Test fee configuration and the cascade resolution order."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _create_user('admin_fee', first_name='Admin', last_name='Fee')
        _assign_role(cls.admin, Role.ADMIN)
        _assign_role(cls.admin, Role.HEAD_OF_INSTITUTE)

        cls.school = _setup_school_with_subscription(cls.admin, 'Fee School')

        cls.subject = Subject.objects.create(name='English', slug='english', school=cls.school)
        cls.department = Department.objects.create(
            school=cls.school, name='English', slug='english',
            default_fee=Decimal('20.00'),
        )
        DepartmentSubject.objects.create(department=cls.department, subject=cls.subject)

        cls.classroom = _create_classroom(
            cls.school, cls.department, cls.subject, name='English 101',
        )

        cls.student = _create_user('student_fee', first_name='Charlie', last_name='Fee')
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)
        cls.class_student = ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_set_department_fee(self):
        """Department default_fee is used when no class/student override exists."""
        from classroom.fee_utils import get_effective_fee_for_student

        fee = get_effective_fee_for_student(self.class_student)
        self.assertEqual(fee, Decimal('20.00'))

    def test_student_fee_override(self):
        """A ClassStudent.fee_override takes precedence over department fee."""
        from classroom.fee_utils import get_effective_fee_for_student

        self.class_student.fee_override = Decimal('15.00')
        self.class_student.save(update_fields=['fee_override'])

        fee = get_effective_fee_for_student(self.class_student)
        self.assertEqual(fee, Decimal('15.00'))

        # Cleanup
        self.class_student.fee_override = None
        self.class_student.save(update_fields=['fee_override'])

    def test_fee_cascade_order(self):
        """
        Fee resolution cascade: ClassStudent > ClassRoom > Department.
        The most specific override wins.
        """
        from classroom.fee_utils import get_effective_fee_for_student

        # 1. Department default = 20
        fee = get_effective_fee_for_student(self.class_student)
        self.assertEqual(fee, Decimal('20.00'))

        # 2. ClassRoom override = 30 (overrides department)
        self.classroom.fee_override = Decimal('30.00')
        self.classroom.save(update_fields=['fee_override'])
        fee = get_effective_fee_for_student(self.class_student)
        self.assertEqual(fee, Decimal('30.00'))

        # 3. ClassStudent override = 10 (overrides classroom and department)
        self.class_student.fee_override = Decimal('10.00')
        self.class_student.save(update_fields=['fee_override'])
        fee = get_effective_fee_for_student(self.class_student)
        self.assertEqual(fee, Decimal('10.00'))

        # Cleanup
        self.class_student.fee_override = None
        self.class_student.save(update_fields=['fee_override'])
        self.classroom.fee_override = None
        self.classroom.save(update_fields=['fee_override'])

    def test_set_classroom_fee_via_view(self):
        """POST to set_classroom_fee updates the classroom fee_override."""
        url = reverse('set_classroom_fee', kwargs={'classroom_id': self.classroom.id})
        response = self.client.post(url, {'fee_override': '35.50'})
        self.assertEqual(response.status_code, 302)

        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.fee_override, Decimal('35.50'))

        # Cleanup
        self.classroom.fee_override = None
        self.classroom.save(update_fields=['fee_override'])

    def test_add_student_fee_override_via_view(self):
        """POST to add_student_fee_override creates a StudentFeeOverride record."""
        url = reverse('add_student_fee_override')
        response = self.client.post(url, {
            'student_id': self.student.id,
            'daily_rate': '12.50',
            'reason': 'Scholarship',
            'effective_from': '2026-01-01',
        })
        self.assertEqual(response.status_code, 302)

        override = StudentFeeOverride.objects.filter(
            student=self.student, school=self.school,
        ).first()
        self.assertIsNotNone(override)
        self.assertEqual(override.daily_rate, Decimal('12.50'))
        self.assertEqual(override.reason, 'Scholarship')


# ---------------------------------------------------------------------------
# 3. PaymentRecordingTest
# ---------------------------------------------------------------------------

class PaymentRecordingTest(TestCase):
    """Test recording manual payments and their effect on invoice status."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _create_user('admin_pay', first_name='Admin', last_name='Pay')
        _assign_role(cls.admin, Role.ADMIN)
        _assign_role(cls.admin, Role.HEAD_OF_INSTITUTE)

        cls.school = _setup_school_with_subscription(cls.admin, 'Pay School')

        cls.subject = Subject.objects.create(name='Science', slug='science', school=cls.school)
        cls.department = Department.objects.create(
            school=cls.school, name='Science', slug='science',
            default_fee=Decimal('30.00'),
        )
        DepartmentSubject.objects.create(department=cls.department, subject=cls.subject)

        cls.classroom = _create_classroom(
            cls.school, cls.department, cls.subject, name='Science 101',
        )

        cls.teacher = _create_user('teacher_pay', first_name='Teacher', last_name='Pay')
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        cls.student = _create_user('student_pay', first_name='Dana', last_name='Pay')
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def _generate_and_issue_invoice(self):
        """Helper: generate and issue a single invoice for self.student."""
        period_start = datetime.date(2026, 4, 1)
        period_end = datetime.date(2026, 4, 10)

        # Create 3 completed sessions with attendance
        for day_offset in (1, 4, 7):
            session_date = datetime.date(2026, 4, day_offset)
            session = _create_completed_session(self.classroom, session_date, self.teacher)
            _mark_attendance(session, self.student, 'present', self.teacher)

        self.client.post(reverse('generate_invoices'), {
            'billing_period_start': str(period_start),
            'billing_period_end': str(period_end),
            'attendance_mode': 'all_class_days',
        })

        draft_ids = list(
            Invoice.objects.filter(school=self.school, status='draft')
            .values_list('id', flat=True)
        )
        session = self.client.session
        session['draft_invoice_ids'] = draft_ids
        session.save()
        self.client.post(reverse('issue_invoices'))

        return Invoice.objects.filter(
            school=self.school, student=self.student, status='issued',
        ).first()

    def test_record_manual_payment(self):
        """POST to record_manual_payment creates an InvoicePayment."""
        invoice = self._generate_and_issue_invoice()
        self.assertIsNotNone(invoice)

        url = reverse('record_manual_payment', kwargs={'invoice_id': invoice.id})
        response = self.client.post(url, {
            'amount': '50.00',
            'payment_date': '2026-04-15',
            'payment_method': 'cash',
            'notes': 'Partial payment',
        })
        self.assertEqual(response.status_code, 302)

        payment = InvoicePayment.objects.filter(invoice=invoice).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('50.00'))
        self.assertEqual(payment.payment_method, 'cash')
        self.assertEqual(payment.status, 'confirmed')

    def test_payment_updates_invoice_status(self):
        """Paying the full amount transitions invoice status to paid."""
        invoice = self._generate_and_issue_invoice()
        self.assertIsNotNone(invoice)
        full_amount = invoice.amount

        url = reverse('record_manual_payment', kwargs={'invoice_id': invoice.id})
        self.client.post(url, {
            'amount': str(full_amount),
            'payment_date': '2026-04-15',
            'payment_method': 'bank_transfer',
        })

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'paid')

    def test_partial_payment_updates_invoice_status(self):
        """A partial payment transitions invoice to partially_paid."""
        invoice = self._generate_and_issue_invoice()
        self.assertIsNotNone(invoice)
        partial = invoice.amount / 2

        url = reverse('record_manual_payment', kwargs={'invoice_id': invoice.id})
        self.client.post(url, {
            'amount': str(partial),
            'payment_date': '2026-04-15',
            'payment_method': 'cash',
        })

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'partially_paid')

    def test_overpayment_creates_credit(self):
        """Paying more than the invoice amount creates a CreditTransaction."""
        invoice = self._generate_and_issue_invoice()
        self.assertIsNotNone(invoice)
        overpay_amount = invoice.amount + Decimal('20.00')

        url = reverse('record_manual_payment', kwargs={'invoice_id': invoice.id})
        self.client.post(url, {
            'amount': str(overpay_amount),
            'payment_date': '2026-04-15',
            'payment_method': 'bank_transfer',
        })

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'paid')

        credit = CreditTransaction.objects.filter(
            student=self.student, school=self.school, reason='overpayment',
        ).first()
        self.assertIsNotNone(credit)
        self.assertEqual(credit.amount, Decimal('20.00'))


# ---------------------------------------------------------------------------
# 4. ParentPortalTest
# ---------------------------------------------------------------------------

class ParentPortalTest(TestCase):
    """Test parent portal views: dashboard, invoices, progress, access controls."""

    @classmethod
    def setUpTestData(cls):
        # Admin
        cls.admin = _create_user('admin_parent', first_name='Admin', last_name='Parent')
        _assign_role(cls.admin, Role.ADMIN)
        _assign_role(cls.admin, Role.HEAD_OF_INSTITUTE)

        cls.school = _setup_school_with_subscription(cls.admin, 'Parent School')

        # Teacher
        cls.teacher = _create_user('teacher_parent', first_name='Teacher', last_name='PT')
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        # Department, subject
        cls.subject = Subject.objects.create(name='Art', slug='art', school=cls.school)
        cls.department = Department.objects.create(
            school=cls.school, name='Art', slug='art',
            default_fee=Decimal('20.00'),
        )
        DepartmentSubject.objects.create(department=cls.department, subject=cls.subject)

        # Classroom
        cls.classroom = _create_classroom(
            cls.school, cls.department, cls.subject, name='Art 101',
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        # Student (child)
        cls.student = _create_user('child1', first_name='Emma', last_name='PT')
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

        # Another student (not linked to parent)
        cls.other_student = _create_user('child_other', first_name='Other', last_name='Kid')
        _assign_role(cls.other_student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.other_student)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.other_student, is_active=True,
        )

        # Parent
        cls.parent = _create_user('parent1', first_name='ParentUser', last_name='PT')
        _assign_role(cls.parent, Role.PARENT)
        ParentStudent.objects.create(
            parent=cls.parent,
            student=cls.student,
            school=cls.school,
            relationship='mother',
            is_active=True,
        )

        # Create sessions + attendance
        for day_offset in (2, 5, 9):
            session_date = datetime.date(2026, 3, day_offset)
            session = _create_completed_session(cls.classroom, session_date, cls.teacher)
            _mark_attendance(session, cls.student, 'present', cls.teacher)
            _mark_attendance(session, cls.other_student, 'present', cls.teacher)

        # Create an issued invoice for the student
        cls.invoice = Invoice.objects.create(
            invoice_number='INV-2026-0001',
            school=cls.school,
            student=cls.student,
            billing_period_start=datetime.date(2026, 3, 1),
            billing_period_end=datetime.date(2026, 3, 15),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('60.00'),
            amount=Decimal('60.00'),
            status='issued',
            issued_at=timezone.now(),
            due_date=datetime.date(2026, 4, 14),
        )
        InvoiceLineItem.objects.create(
            invoice=cls.invoice,
            classroom=cls.classroom,
            department=cls.department,
            daily_rate=Decimal('20.00'),
            rate_source='department_default',
            sessions_held=3,
            sessions_attended=3,
            sessions_charged=3,
            line_amount=Decimal('60.00'),
        )

        # Create an issued invoice for the other student (parent should not see)
        cls.other_invoice = Invoice.objects.create(
            invoice_number='INV-2026-0002',
            school=cls.school,
            student=cls.other_student,
            billing_period_start=datetime.date(2026, 3, 1),
            billing_period_end=datetime.date(2026, 3, 15),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('60.00'),
            amount=Decimal('60.00'),
            status='issued',
            issued_at=timezone.now(),
            due_date=datetime.date(2026, 4, 14),
        )

        # Progress records for the student
        cls.level = Level.objects.create(level_number=200, display_name='Level 200', school=cls.school)
        cls.criteria = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject,
            level=cls.level,
            name='Colour Theory Basics',
            status='approved',
            created_by=cls.teacher,
        )
        ProgressRecord.objects.create(
            student=cls.student,
            criteria=cls.criteria,
            status='achieved',
            recorded_by=cls.teacher,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.parent)

    def test_parent_dashboard_loads(self):
        """Parent dashboard returns 200 and shows child summary."""
        url = reverse('parent_dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Emma')

    def test_parent_sees_student_invoices(self):
        """Parent invoices page lists invoices for the linked child."""
        url = reverse('parent_invoices')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-2026-0001')

    def test_parent_sees_invoice_detail(self):
        """Parent can view detail for their child's invoice."""
        url = reverse('parent_invoice_detail', kwargs={'invoice_id': self.invoice.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-2026-0001')

    def test_parent_sees_student_progress(self):
        """Parent progress page shows the child's progress records."""
        url = reverse('parent_progress')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Colour Theory Basics')

    def test_parent_cannot_see_other_students_invoice(self):
        """Parent cannot view invoice for a student they are not linked to."""
        url = reverse('parent_invoice_detail', kwargs={'invoice_id': self.other_invoice.id})
        response = self.client.get(url)
        # Should be 404 because get_object_or_404 filters by active child
        self.assertEqual(response.status_code, 404)

    def test_parent_invoice_list_excludes_other_students(self):
        """Parent invoices page does not show invoices for unlinked students."""
        url = reverse('parent_invoices')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'INV-2026-0002')

    def test_unauthenticated_parent_redirected(self):
        """An unauthenticated user cannot access parent portal."""
        self.client.logout()
        url = reverse('parent_dashboard')
        response = self.client.get(url)
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_non_parent_role_denied(self):
        """A user without the PARENT role cannot access parent portal."""
        non_parent = _create_user('not_a_parent')
        _assign_role(non_parent, Role.STUDENT)
        self.client.force_login(non_parent)

        url = reverse('parent_dashboard')
        response = self.client.get(url)
        # Should redirect to public_home (denied by RoleRequiredMixin)
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# 5. InvoiceNotificationTest
# ---------------------------------------------------------------------------

class InvoiceNotificationTest(TestCase):
    """Test that issuing invoices triggers email notifications."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _create_user('admin_notif', first_name='Admin', last_name='Notif')
        _assign_role(cls.admin, Role.ADMIN)
        _assign_role(cls.admin, Role.HEAD_OF_INSTITUTE)

        cls.school = _setup_school_with_subscription(cls.admin, 'Notif School')

        cls.teacher = _create_user('teacher_notif', first_name='Teacher', last_name='Notif')
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        cls.subject = Subject.objects.create(name='History', slug='history', school=cls.school)
        cls.department = Department.objects.create(
            school=cls.school, name='History', slug='history',
            default_fee=Decimal('18.00'),
        )
        DepartmentSubject.objects.create(department=cls.department, subject=cls.subject)

        cls.classroom = _create_classroom(
            cls.school, cls.department, cls.subject, name='History 101',
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        cls.student = _create_user(
            'student_notif', first_name='Frank', last_name='Notif',
            email='frank@example.com',
        )
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

        # Sessions + attendance
        for day_offset in (2, 5):
            session_date = datetime.date(2026, 5, day_offset)
            session = _create_completed_session(cls.classroom, session_date, cls.teacher)
            _mark_attendance(session, cls.student, 'present', cls.teacher)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_issuing_invoice_sends_email(self):
        """Issuing invoices sends an email notification (captured by Django mail outbox)."""
        from django.core import mail

        # Generate drafts
        self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '2026-05-01',
            'billing_period_end': '2026-05-10',
            'attendance_mode': 'all_class_days',
        })

        draft_ids = list(
            Invoice.objects.filter(school=self.school, status='draft')
            .values_list('id', flat=True)
        )
        self.assertTrue(len(draft_ids) > 0)

        session = self.client.session
        session['draft_invoice_ids'] = draft_ids
        session.save()

        # Issue invoices
        self.client.post(reverse('issue_invoices'))

        # Verify invoice was issued
        invoice = Invoice.objects.filter(
            school=self.school, student=self.student,
        ).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.status, 'issued')

        # Check that email was sent (Django test runner uses locmem backend)
        self.assertGreaterEqual(len(mail.outbox), 1)
        sent_to = [m.to[0] for m in mail.outbox if m.to]
        self.assertIn('frank@example.com', sent_to)

    def test_issued_invoice_has_due_date(self):
        """Issued invoice has a due_date calculated from school.invoice_due_days."""
        self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '2026-05-01',
            'billing_period_end': '2026-05-10',
            'attendance_mode': 'all_class_days',
        })

        draft_ids = list(
            Invoice.objects.filter(school=self.school, status='draft')
            .values_list('id', flat=True)
        )
        session = self.client.session
        session['draft_invoice_ids'] = draft_ids
        session.save()

        self.client.post(reverse('issue_invoices'))

        invoice = Invoice.objects.filter(
            school=self.school, student=self.student, status='issued',
        ).first()
        self.assertIsNotNone(invoice)
        self.assertIsNotNone(invoice.due_date)

        # Due date should be ~30 days from issue (school.invoice_due_days=30)
        expected_due = invoice.issued_at.date() + datetime.timedelta(days=30)
        self.assertEqual(invoice.due_date, expected_due)


# ---------------------------------------------------------------------------
# 6. InvoiceListAndDetailTest
# ---------------------------------------------------------------------------

class InvoiceListAndDetailTest(TestCase):
    """Test invoice list and detail views for admin users."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _create_user('admin_list', first_name='Admin', last_name='List')
        _assign_role(cls.admin, Role.ADMIN)
        _assign_role(cls.admin, Role.HEAD_OF_INSTITUTE)

        cls.school = _setup_school_with_subscription(cls.admin, 'List School')

        cls.student = _create_user('student_list', first_name='Grace', last_name='List')
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        cls.subject = Subject.objects.create(name='Music', slug='music', school=cls.school)
        cls.department = Department.objects.create(
            school=cls.school, name='Music', slug='music',
            default_fee=Decimal('22.00'),
        )

        cls.classroom = _create_classroom(
            cls.school, cls.department, cls.subject, name='Music 101',
        )

        cls.invoice = Invoice.objects.create(
            invoice_number='INV-2026-L001',
            school=cls.school,
            student=cls.student,
            billing_period_start=datetime.date(2026, 3, 1),
            billing_period_end=datetime.date(2026, 3, 31),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('110.00'),
            amount=Decimal('110.00'),
            status='issued',
            issued_at=timezone.now(),
            due_date=datetime.date(2026, 4, 30),
        )
        InvoiceLineItem.objects.create(
            invoice=cls.invoice,
            classroom=cls.classroom,
            department=cls.department,
            daily_rate=Decimal('22.00'),
            rate_source='department_default',
            sessions_held=5,
            sessions_attended=5,
            sessions_charged=5,
            line_amount=Decimal('110.00'),
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_invoice_list_loads(self):
        """GET invoice_list returns 200 and shows the invoice."""
        url = reverse('invoice_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-2026-L001')

    def test_invoice_list_filter_by_status(self):
        """invoice_list can be filtered by status query parameter."""
        url = reverse('invoice_list') + '?status=issued'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-2026-L001')

        url = reverse('invoice_list') + '?status=paid'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'INV-2026-L001')

    def test_invoice_detail_loads(self):
        """GET invoice_detail returns 200 with invoice data."""
        url = reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-2026-L001')
        self.assertContains(response, 'Grace')

    def test_invoice_detail_shows_line_items(self):
        """Invoice detail page includes line item details."""
        url = reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Music 101')
