"""Tests for parent portal views (CPP-67/68/69)."""
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, Department, DepartmentSubject, Subject,
    ClassRoom, ClassStudent,
    ParentStudent, Invoice, InvoiceLineItem, InvoicePayment,
    ProgressCriteria, ProgressRecord, Level,
)
from attendance.models import ClassSession, StudentAttendance


class ParentPortalTestBase(TestCase):
    """Shared fixtures for parent portal tests."""

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )

        # Admin & school
        cls.admin_user = CustomUser.objects.create_user(
            'admin', 'admin@test.com', 'pass1234',
        )
        cls.admin_user.roles.add(cls.admin_role)
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )

        # Student
        cls.student = CustomUser.objects.create_user(
            'student1', 'student@test.com', 'pass1234',
            first_name='Zara', last_name='Student',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        # Parent linked to student
        cls.parent = CustomUser.objects.create_user(
            'parent1', 'parent@test.com', 'pass1234',
            first_name='Jane', last_name='Parent',
        )
        cls.parent.roles.add(cls.parent_role)
        cls.link = ParentStudent.objects.create(
            parent=cls.parent, student=cls.student,
            school=cls.school, relationship='mother',
        )

        # Unlinked parent (should not see student data)
        cls.other_parent = CustomUser.objects.create_user(
            'other_parent', 'other@test.com', 'pass1234',
        )
        cls.other_parent.roles.add(cls.parent_role)

        # Class + enrollment
        cls.maths, _ = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.classroom = ClassRoom.objects.create(
            name='Maths Year 7', school=cls.school, subject=cls.maths,
        )
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student,
        )

        # Sessions + attendance
        cls.session1 = ClassSession.objects.create(
            classroom=cls.classroom, date=date(2026, 3, 10),
            start_time=time(9, 0), end_time=time(10, 0),
            status='completed',
        )
        cls.session2 = ClassSession.objects.create(
            classroom=cls.classroom, date=date(2026, 3, 11),
            start_time=time(9, 0), end_time=time(10, 0),
            status='completed',
        )
        StudentAttendance.objects.create(
            student=cls.student, session=cls.session1,
            status='present', marked_by=cls.admin_user,
        )
        StudentAttendance.objects.create(
            student=cls.student, session=cls.session2,
            status='late', marked_by=cls.admin_user,
        )

        # Invoice
        cls.invoice = Invoice.objects.create(
            school=cls.school, student=cls.student,
            invoice_number='INV-001',
            billing_period_start=date(2026, 3, 1),
            billing_period_end=date(2026, 3, 31),
            calculated_amount=Decimal('100.00'),
            amount=Decimal('100.00'),
            status='issued',
        )
        InvoiceLineItem.objects.create(
            invoice=cls.invoice, classroom=cls.classroom,
            sessions_held=10, sessions_attended=8, sessions_charged=8,
            daily_rate=Decimal('12.50'), line_amount=Decimal('100.00'),
        )

        # Payment
        cls.payment = InvoicePayment.objects.create(
            invoice=cls.invoice, school=cls.school,
            student=cls.student, amount=Decimal('50.00'),
            payment_date=date(2026, 3, 15),
            payment_method='bank_transfer',
            status='confirmed',
        )

        # Progress
        cls.level, _ = Level.objects.get_or_create(
            level_number=7,
            defaults={'display_name': 'Year 7'},
        )
        cls.criteria = ProgressCriteria.objects.create(
            school=cls.school, subject=cls.maths, level=cls.level,
            name='Can add fractions', status='approved',
        )
        cls.progress_record = ProgressRecord.objects.create(
            student=cls.student, criteria=cls.criteria,
            status='achieved', recorded_by=cls.admin_user,
        )


class ParentDashboardTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='pass1234')

    def test_dashboard_loads(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Welcome, Jane')

    def test_dashboard_shows_child_stats(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, 'Zara Student')
        self.assertContains(resp, 'Test School')

    def test_dashboard_requires_parent_role(self):
        self.client.login(username='student1', password='pass1234')
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotEqual(resp.status_code, 200)

    def test_dashboard_anonymous_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)


class ParentSwitchChildTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='pass1234')

    def test_switch_child_updates_session(self):
        url = reverse('parent_switch_child', args=[self.student.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            self.client.session.get('active_child_id'),
            self.student.id,
        )

    def test_switch_unlinked_child_ignored(self):
        other_student = CustomUser.objects.create_user('s2', 's2@t.com', 'pass1234')
        url = reverse('parent_switch_child', args=[other_student.id])
        self.client.post(url)
        # Should NOT set the unlinked student as active
        self.assertNotEqual(
            self.client.session.get('active_child_id'),
            other_student.id,
        )


class ParentInvoicesTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='pass1234')

    def test_invoice_list_loads(self):
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'INV-001')

    def test_invoice_list_excludes_drafts(self):
        Invoice.objects.create(
            school=self.school, student=self.student,
            invoice_number='INV-DRAFT',
            billing_period_start=date(2026, 2, 1),
            billing_period_end=date(2026, 2, 28),
            calculated_amount=Decimal('50.00'),
            amount=Decimal('50.00'),
            status='draft',
        )
        resp = self.client.get(reverse('parent_invoices'))
        self.assertNotContains(resp, 'INV-DRAFT')

    def test_invoice_detail_loads(self):
        resp = self.client.get(reverse('parent_invoice_detail', args=[self.invoice.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'INV-001')
        self.assertContains(resp, '100.00')

    def test_invoice_detail_shows_line_items(self):
        resp = self.client.get(reverse('parent_invoice_detail', args=[self.invoice.id]))
        self.assertContains(resp, 'Maths Year 7')

    def test_invoice_detail_shows_payments(self):
        resp = self.client.get(reverse('parent_invoice_detail', args=[self.invoice.id]))
        self.assertContains(resp, '50.00')

    def test_unlinked_parent_cannot_see_invoice(self):
        self.client.login(username='other_parent', password='pass1234')
        resp = self.client.get(reverse('parent_invoice_detail', args=[self.invoice.id]))
        # Unlinked parent has no active child, so view redirects
        self.assertIn(resp.status_code, [302, 404])

    def test_draft_invoice_returns_404(self):
        draft = Invoice.objects.create(
            school=self.school, student=self.student,
            invoice_number='INV-D2',
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            calculated_amount=Decimal('50.00'),
            amount=Decimal('50.00'),
            status='draft',
        )
        resp = self.client.get(reverse('parent_invoice_detail', args=[draft.id]))
        self.assertEqual(resp.status_code, 404)


class ParentPaymentHistoryTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='pass1234')

    def test_payment_history_loads(self):
        resp = self.client.get(reverse('parent_payment_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '50.00')

    def test_payment_history_links_to_invoice(self):
        resp = self.client.get(reverse('parent_payment_history'))
        self.assertContains(resp, 'INV-001')


class ParentAttendanceTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='pass1234')

    def test_attendance_loads(self):
        resp = self.client.get(reverse('parent_attendance'))
        self.assertEqual(resp.status_code, 200)

    def test_attendance_shows_stats(self):
        resp = self.client.get(reverse('parent_attendance'))
        # 2 sessions, 1 present + 1 late = 100% attendance
        self.assertContains(resp, '100%')

    def test_attendance_shows_class_summary(self):
        resp = self.client.get(reverse('parent_attendance'))
        self.assertContains(resp, 'Maths Year 7')

    def test_attendance_shows_records(self):
        resp = self.client.get(reverse('parent_attendance'))
        self.assertContains(resp, 'Present')
        self.assertContains(resp, 'Late')


class ParentProgressTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='pass1234')

    def test_progress_loads(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(resp.status_code, 200)

    def test_progress_shows_criteria(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertContains(resp, 'Can add fractions')

    def test_progress_shows_achieved_status(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertContains(resp, 'Achieved')

    def test_progress_shows_overall_stats(self):
        resp = self.client.get(reverse('parent_progress'))
        # 1 total, 1 achieved
        self.assertContains(resp, '1')


class ParentDataIsolationTest(ParentPortalTestBase):
    """Security: parent can only see their own linked children's data."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='other_parent', password='pass1234')

    def test_unlinked_parent_sees_empty_invoices(self):
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'INV-001')

    def test_unlinked_parent_sees_empty_attendance(self):
        resp = self.client.get(reverse('parent_attendance'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Maths Year 7')

    def test_unlinked_parent_sees_empty_progress(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Can add fractions')

    def test_unlinked_parent_invoice_detail_blocked(self):
        resp = self.client.get(reverse('parent_invoice_detail', args=[self.invoice.id]))
        # Unlinked parent has no active child, so view redirects (not 200)
        self.assertNotEqual(resp.status_code, 200)


class ParentURLTest(TestCase):

    def test_all_parent_urls_resolve(self):
        self.assertTrue(reverse('parent_dashboard'))
        self.assertTrue(reverse('parent_invoices'))
        self.assertTrue(reverse('parent_invoice_detail', args=[1]))
        self.assertTrue(reverse('parent_payment_history'))
        self.assertTrue(reverse('parent_attendance'))
        self.assertTrue(reverse('parent_progress'))
        self.assertTrue(reverse('parent_switch_child', args=[1]))
