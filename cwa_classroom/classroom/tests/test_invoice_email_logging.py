"""
Unit tests for CPP-242 — Invoice email logging, school scoping, and failure
classification.

Covers:
  - EmailLog.school FK written by send_templated_email
  - EmailLog.invoice FK written by _send_invoice_email and _send_invoice_cancelled_email
  - Failed SMTP correctly lands in result['failed'], not result['sent']
  - Guardian emails store recipient_email but leave recipient NULL (Guardian has no user account)
  - EmailDashboardView counts are school-scoped, not global
  - TransactionalEmailLogView: list, type filter, status filter, email search
  - InvoiceDetailView passes email_logs queryset to template context
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom import invoicing_services as svc
from classroom.email_service import send_templated_email
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, DepartmentSubject,
    EmailLog, Guardian, Invoice, InvoiceLineItem, ParentStudent, School,
    SchoolStudent, SchoolTeacher, StudentGuardian, Subject,
)
from classroom.tests.test_e2e_invoicing import (
    _assign_role, _create_classroom, _create_user,
)


# ---------------------------------------------------------------------------
# Shared test-fixture helpers
# ---------------------------------------------------------------------------

def _make_plan(suffix=''):
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f'test-plan-log{suffix}',
        defaults={
            'name': f'Test Plan Log {suffix}',
            'price': Decimal('0.00'),
            'class_limit': 100,
            'student_limit': 100,
            'invoice_limit_yearly': 1000,
            'extra_invoice_rate': Decimal('0.00'),
        },
    )
    return plan


def _build_school(suffix=''):
    admin = _create_user(
        f'log_admin{suffix}', first_name='Log', last_name='Admin',
    )
    _assign_role(admin, Role.ADMIN)
    _assign_role(admin, Role.HEAD_OF_INSTITUTE)
    school = School.objects.create(
        name=f'Log School {suffix}',
        slug=f'log-school-{suffix}',
        admin=admin,
        is_active=True,
        invoice_due_days=30,
        invoice_recipient_policy='parents_and_student',
    )
    SchoolSubscription.objects.create(
        school=school, plan=_make_plan(suffix),
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    return admin, school


def _build_full_context(suffix=''):
    """Return (admin, school, student, parent, guardian, invoice)."""
    admin, school = _build_school(suffix)

    subject_obj = Subject.objects.create(
        name=f'Maths{suffix}', slug=f'maths-log{suffix}', school=school,
    )
    department = Department.objects.create(
        school=school, name=f'Dept{suffix}', slug=f'dept-log{suffix}',
        default_fee=Decimal('25.00'),
    )
    DepartmentSubject.objects.create(department=department, subject=subject_obj)
    classroom = _create_classroom(school, department, subject_obj, name='Year 5')
    teacher = _create_user(f'log_teacher{suffix}')
    _assign_role(teacher, Role.TEACHER)
    SchoolTeacher.objects.update_or_create(
        school=school, teacher=teacher, defaults={'role': 'teacher'},
    )
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)

    student = _create_user(
        f'log_student{suffix}',
        email=f'student_log{suffix}@example.com',
        first_name='Student', last_name='Log',
    )
    _assign_role(student, Role.STUDENT)
    ss = SchoolStudent.objects.create(school=school, student=student)
    ClassStudent.objects.create(classroom=classroom, student=student, is_active=True)

    parent = _create_user(
        f'log_parent{suffix}',
        email=f'parent_log{suffix}@example.com',
        first_name='Parent', last_name='Log',
    )
    _assign_role(parent, Role.PARENT)
    ParentStudent.objects.create(
        parent=parent, student=student, school=school,
        relationship='mother', is_active=True,
    )

    guardian = Guardian.objects.create(
        school=school,
        email=f'guardian_log{suffix}@example.com',
        first_name='Guardian', last_name='Log',
    )
    StudentGuardian.objects.create(student=student, guardian=guardian)

    invoice = Invoice.objects.create(
        invoice_number=f'INV-LOG{suffix}',
        school=school, student=student,
        billing_period_start=datetime.date(2026, 4, 1),
        billing_period_end=datetime.date(2026, 4, 30),
        attendance_mode='all_class_days', billing_type='upfront',
        period_type='custom',
        calculated_amount=Decimal('100.00'), amount=Decimal('100.00'),
        status='issued', issued_at=timezone.now(),
        created_by=admin, due_date=datetime.date(2026, 5, 30),
    )
    InvoiceLineItem.objects.create(
        invoice=invoice, classroom=classroom, department=department,
        daily_rate=Decimal('25.00'), rate_source='class_default',
        sessions_held=4, sessions_attended=4, sessions_charged=4,
        line_amount=Decimal('100.00'),
    )
    return admin, school, student, parent, guardian, invoice


# ---------------------------------------------------------------------------
# 1. send_templated_email stores school FK
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestEmailLogSchoolFKWritten(TestCase):

    def setUp(self):
        _, self.school = _build_school('sch')

    def test_school_stored_on_sent_log(self):
        send_templated_email(
            recipient_email='x@example.com',
            subject='Test school FK',
            template_name='email/transactional/general_notification.html',
            context={'notification_message': 'hi', 'notification_type': 'general', 'notification_link': ''},
            notification_type='general',
            school=self.school,
        )
        log = EmailLog.objects.get(subject='Test school FK')
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.status, 'sent')

    def test_school_stored_on_failed_log(self):
        with patch('classroom.email_service.EmailMultiAlternatives.send', side_effect=Exception('SMTP down')):
            send_templated_email(
                recipient_email='x@example.com',
                subject='Test school FK fail',
                template_name='email/transactional/general_notification.html',
                context={'notification_message': 'hi', 'notification_type': 'general', 'notification_link': ''},
                notification_type='general',
                school=self.school,
                fail_silently=True,
            )
        log = EmailLog.objects.get(subject='Test school FK fail')
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.status, 'failed')
        self.assertIn('SMTP down', log.error_message)

    def test_no_school_stores_null(self):
        send_templated_email(
            recipient_email='x@example.com',
            subject='Test no school',
            template_name='email/transactional/general_notification.html',
            context={'notification_message': 'hi', 'notification_type': 'general', 'notification_link': ''},
            notification_type='general',
            school=None,
        )
        log = EmailLog.objects.get(subject='Test no school')
        self.assertIsNone(log.school)


# ---------------------------------------------------------------------------
# 2. _send_invoice_email writes invoice FK and correct recipients
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestInvoiceEmailLogInvoiceFK(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school, cls.student, cls.parent, cls.guardian, cls.invoice = (
            _build_full_context('invfk')
        )

    def test_all_logs_linked_to_invoice(self):
        svc._send_invoice_email(self.invoice)
        logs = EmailLog.objects.filter(invoice=self.invoice)
        self.assertGreater(logs.count(), 0, 'Expected at least one EmailLog linked to invoice')
        for log in logs:
            self.assertEqual(log.invoice, self.invoice)

    def test_all_logs_linked_to_school(self):
        svc._send_invoice_email(self.invoice)
        logs = EmailLog.objects.filter(invoice=self.invoice)
        for log in logs:
            self.assertEqual(log.school, self.school)

    def test_student_email_logged(self):
        svc._send_invoice_email(self.invoice)
        self.assertTrue(
            EmailLog.objects.filter(invoice=self.invoice, recipient_email=self.student.email).exists()
        )

    def test_parent_email_logged(self):
        svc._send_invoice_email(self.invoice)
        self.assertTrue(
            EmailLog.objects.filter(invoice=self.invoice, recipient_email=self.parent.email).exists()
        )

    def test_guardian_email_logged(self):
        svc._send_invoice_email(self.invoice)
        log = EmailLog.objects.filter(
            invoice=self.invoice, recipient_email=self.guardian.email,
        ).first()
        self.assertIsNotNone(log, 'Guardian email not found in EmailLog')
        # Guardian has no CustomUser account — recipient FK is intentionally NULL
        self.assertIsNone(log.recipient)

    def test_notification_type_is_invoice(self):
        svc._send_invoice_email(self.invoice)
        logs = EmailLog.objects.filter(invoice=self.invoice)
        for log in logs:
            self.assertEqual(log.notification_type, 'invoice')


# ---------------------------------------------------------------------------
# 3. Return-value fix: failed SMTP → result['failed'], not result['sent']
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestInvoiceEmailFailureClassification(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school, cls.student, cls.parent, cls.guardian, cls.invoice = (
            _build_full_context('fail')
        )

    def test_smtp_failure_lands_in_failed_not_sent(self):
        with patch(
            'classroom.email_service.EmailMultiAlternatives.send',
            side_effect=Exception('Connection refused'),
        ):
            result = svc._send_invoice_email(self.invoice)

        self.assertEqual(result['sent'], [], 'sent should be empty when SMTP fails')
        self.assertGreater(len(result['failed']), 0, 'failed should contain recipient emails')
        self.assertIn(self.student.email, result['failed'])

    def test_smtp_failure_writes_failed_log(self):
        with patch(
            'classroom.email_service.EmailMultiAlternatives.send',
            side_effect=Exception('SMTP timeout'),
        ):
            svc._send_invoice_email(self.invoice)

        failed_logs = EmailLog.objects.filter(invoice=self.invoice, status='failed')
        self.assertGreater(failed_logs.count(), 0)
        self.assertIn('SMTP timeout', failed_logs.first().error_message)

    def test_success_lands_in_sent_not_failed(self):
        result = svc._send_invoice_email(self.invoice)
        self.assertIn(self.student.email, result['sent'])
        self.assertEqual(result['failed'], [])


# ---------------------------------------------------------------------------
# 4. _send_invoice_cancelled_email writes invoice FK
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestCancelledEmailInvoiceFK(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school, cls.student, cls.parent, cls.guardian, cls.invoice = (
            _build_full_context('cancel')
        )

    def test_cancelled_logs_linked_to_invoice(self):
        svc._send_invoice_cancelled_email(self.invoice, reason='Test cancel', credit_returned=Decimal('0'))
        logs = EmailLog.objects.filter(invoice=self.invoice, notification_type='invoice_cancelled')
        self.assertGreater(logs.count(), 0)
        for log in logs:
            self.assertEqual(log.invoice, self.invoice)
            self.assertEqual(log.school, self.school)

    def test_guardian_email_logged_on_cancel(self):
        svc._send_invoice_cancelled_email(self.invoice, reason='Test', credit_returned=Decimal('0'))
        log = EmailLog.objects.filter(
            invoice=self.invoice,
            notification_type='invoice_cancelled',
            recipient_email=self.guardian.email,
        ).first()
        self.assertIsNotNone(log)
        # Guardian has no CustomUser account — recipient FK is intentionally NULL
        self.assertIsNone(log.recipient)


# ---------------------------------------------------------------------------
# 5. EmailDashboardView: school-scoped counts
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestEmailDashboardSchoolScoped(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin_a, cls.school_a = _build_school('dasha')
        cls.admin_b, cls.school_b = _build_school('dashb')

    def test_sent_count_scoped_to_school(self):
        EmailLog.objects.create(
            school=self.school_a, recipient_email='a@a.com',
            subject='S', notification_type='general', status='sent',
        )
        EmailLog.objects.create(
            school=self.school_b, recipient_email='b@b.com',
            subject='S', notification_type='general', status='sent',
        )
        c = Client()
        c.force_login(self.admin_a)
        resp = c.get(reverse('email_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_sent'], 1)

    def test_failed_count_scoped_to_school(self):
        EmailLog.objects.create(
            school=self.school_a, recipient_email='a@a.com',
            subject='F', notification_type='general', status='failed', error_message='err',
        )
        EmailLog.objects.create(
            school=self.school_b, recipient_email='b@b.com',
            subject='F', notification_type='general', status='failed', error_message='err',
        )
        c = Client()
        c.force_login(self.admin_a)
        resp = c.get(reverse('email_dashboard'))
        self.assertEqual(resp.context['total_failed'], 1)


# ---------------------------------------------------------------------------
# 6. TransactionalEmailLogView: list + filters
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestTransactionalEmailLogView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _build_school('logview')
        cls.other_admin, cls.other_school = _build_school('logview2')

        EmailLog.objects.create(
            school=cls.school, recipient_email='inv@test.com',
            subject='Invoice INV-001', notification_type='invoice', status='sent',
        )
        EmailLog.objects.create(
            school=cls.school, recipient_email='enroll@test.com',
            subject='Enrollment approved', notification_type='enrollment_approved', status='sent',
        )
        EmailLog.objects.create(
            school=cls.school, recipient_email='fail@test.com',
            subject='Invoice INV-002', notification_type='invoice', status='failed',
            error_message='SMTP error',
        )
        EmailLog.objects.create(
            school=cls.other_school, recipient_email='other@test.com',
            subject='Other school email', notification_type='invoice', status='sent',
        )

    def _get(self, **params):
        c = Client()
        c.force_login(self.admin)
        return c.get(reverse('email_log_list'), params)

    def test_page_loads(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)

    def test_only_own_school_logs_shown(self):
        resp = self._get()
        emails = [log.recipient_email for log in resp.context['logs']]
        self.assertNotIn('other@test.com', emails)

    def test_no_campaign_logs_shown(self):
        from classroom.models import EmailCampaign
        campaign = EmailCampaign.objects.create(
            name='Test Campaign', subject='Campaign',
            html_body='<p>hi</p>', school=self.school,
            created_by=self.admin,
        )
        EmailLog.objects.create(
            school=self.school, campaign=campaign,
            recipient_email='campaign@test.com', subject='Campaign',
            notification_type='', status='sent',
        )
        resp = self._get()
        emails = [log.recipient_email for log in resp.context['logs']]
        self.assertNotIn('campaign@test.com', emails)

    def test_filter_by_type(self):
        resp = self._get(type='invoice')
        emails = [log.recipient_email for log in resp.context['logs']]
        self.assertIn('inv@test.com', emails)
        self.assertNotIn('enroll@test.com', emails)

    def test_filter_by_status_failed(self):
        resp = self._get(status='failed')
        emails = [log.recipient_email for log in resp.context['logs']]
        self.assertIn('fail@test.com', emails)
        self.assertNotIn('inv@test.com', emails)

    def test_filter_by_email_search(self):
        resp = self._get(q='enroll')
        emails = [log.recipient_email for log in resp.context['logs']]
        self.assertIn('enroll@test.com', emails)
        self.assertNotIn('inv@test.com', emails)

    def test_unauthenticated_redirected(self):
        resp = Client().get(reverse('email_log_list'))
        self.assertRedirects(resp, f'/accounts/login/?next=/admin-dashboard/email/logs/', fetch_redirect_response=False)

    def test_combined_type_and_status_filter(self):
        resp = self._get(type='invoice', status='failed')
        emails = [log.recipient_email for log in resp.context['logs']]
        self.assertIn('fail@test.com', emails)
        self.assertNotIn('inv@test.com', emails)
        self.assertNotIn('enroll@test.com', emails)


# ---------------------------------------------------------------------------
# 7. InvoiceDetailView passes email_logs to context
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestInvoiceDetailEmailLogs(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school, cls.student, cls.parent, cls.guardian, cls.invoice = (
            _build_full_context('detail')
        )

    def test_email_logs_in_context(self):
        EmailLog.objects.create(
            school=self.school, invoice=self.invoice,
            recipient_email=self.student.email,
            subject='Invoice', notification_type='invoice', status='sent',
        )
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('email_logs', resp.context)
        log_emails = [log.recipient_email for log in resp.context['email_logs']]
        self.assertIn(self.student.email, log_emails)

    def test_email_logs_empty_for_unsent_invoice(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('email_logs', resp.context)

    def test_only_this_invoice_logs_shown(self):
        other_invoice = Invoice.objects.create(
            invoice_number='INV-OTHER-DETAIL',
            school=self.school, student=self.student,
            billing_period_start=datetime.date(2026, 5, 1),
            billing_period_end=datetime.date(2026, 5, 31),
            attendance_mode='all_class_days', billing_type='upfront',
            period_type='custom',
            calculated_amount=Decimal('50.00'), amount=Decimal('50.00'),
            status='issued', issued_at=timezone.now(),
            created_by=self.admin, due_date=datetime.date(2026, 6, 30),
        )
        EmailLog.objects.create(
            school=self.school, invoice=self.invoice,
            recipient_email='this@example.com',
            subject='This invoice', notification_type='invoice', status='sent',
        )
        EmailLog.objects.create(
            school=self.school, invoice=other_invoice,
            recipient_email='other@example.com',
            subject='Other invoice', notification_type='invoice', status='sent',
        )
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id}))
        log_emails = [log.recipient_email for log in resp.context['email_logs']]
        self.assertIn('this@example.com', log_emails)
        self.assertNotIn('other@example.com', log_emails)
