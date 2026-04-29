"""
Tests for the Resend Invoice feature: ``resend_invoice_email`` service +
``ResendInvoiceView`` POST endpoint.

Used by admins after a parent's email bounces — they correct the parent's
email and click "Resend" on the invoice list to redeliver.
"""

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from classroom import invoicing_services as svc
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, DepartmentSubject,
    Invoice, InvoiceLineItem, ParentStudent, SchoolStudent, SchoolTeacher,
    Subject,
)

from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import School

from .test_e2e_invoicing import _create_user, _assign_role, _create_classroom


def _setup_school_local(admin, school_name):
    """Local school setup that's safe to call multiple times in one TestCase
    (the shared helper hardcodes the InstitutePlan slug, so it errors on
    duplicate calls within the same DB)."""
    school = School.objects.create(
        name=school_name,
        slug=school_name.lower().replace(' ', '-'),
        admin=admin,
        is_active=True,
        invoice_due_days=30,
    )
    plan, _ = InstitutePlan.objects.get_or_create(
        slug='test-plan-resend',
        defaults={
            'name': 'Test Plan (resend)',
            'price': Decimal('0.00'),
            'class_limit': 100,
            'student_limit': 100,
            'invoice_limit_yearly': 1000,
            'extra_invoice_rate': Decimal('0.00'),
        },
    )
    SchoolSubscription.objects.create(
        school=school, plan=plan,
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    return school


def _build_school_with_invoice(name_suffix=''):
    """Set up a school + student + parent + one issued invoice. Returns ctx."""
    admin = _create_user(
        f'admin_resend{name_suffix}', first_name='Admin', last_name='Resend',
    )
    _assign_role(admin, Role.ADMIN)
    _assign_role(admin, Role.HEAD_OF_INSTITUTE)

    school = _setup_school_local(admin, f'Resend School{name_suffix}')

    teacher = _create_user(f'teacher_resend{name_suffix}')
    _assign_role(teacher, Role.TEACHER)
    SchoolTeacher.objects.update_or_create(
        school=school, teacher=teacher, defaults={'role': 'teacher'},
    )

    subject = Subject.objects.create(
        name=f'Maths{name_suffix}', slug=f'maths{name_suffix}', school=school,
    )
    department = Department.objects.create(
        school=school, name=f'Maths Dept{name_suffix}',
        slug=f'maths-dept{name_suffix}', default_fee=Decimal('25.00'),
    )
    DepartmentSubject.objects.create(department=department, subject=subject)

    classroom = _create_classroom(school, department, subject, name='Year 5 Maths')
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)

    student = _create_user(
        f'student_resend{name_suffix}',
        first_name='Min Htet', last_name='Kyaw',
        email=f'student_resend{name_suffix}@example.com',
    )
    _assign_role(student, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=student)
    ClassStudent.objects.create(
        classroom=classroom, student=student, is_active=True,
    )

    parent = _create_user(
        f'parent_resend{name_suffix}',
        first_name='Parent', last_name='OK',
        email=f'parent_resend{name_suffix}@example.com',
    )
    _assign_role(parent, Role.PARENT)
    ParentStudent.objects.create(
        parent=parent, student=student, school=school,
        relationship='mother', is_active=True,
    )

    # Issued invoice
    invoice = Invoice.objects.create(
        invoice_number=f'INV-RESEND{name_suffix}',
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

    return {
        'admin': admin, 'school': school, 'student': student,
        'parent': parent, 'invoice': invoice, 'classroom': classroom,
    }


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ResendInvoiceEmailServiceTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ctx = _build_school_with_invoice(name_suffix='_svc')

    def setUp(self):
        mail.outbox = []

    def test_resend_issued_invoice_sends_to_student_and_parent(self):
        """Resending an issued invoice emails student + linked parents."""
        result = svc.resend_invoice_email(self.ctx['invoice'])

        sent_lower = {e.lower() for e in result['sent']}
        self.assertIn(self.ctx['student'].email.lower(), sent_lower)
        self.assertIn(self.ctx['parent'].email.lower(), sent_lower)
        self.assertEqual(result['failed'], [])
        self.assertFalse(result['skipped_no_email'])

        # Two emails actually queued by the locmem backend
        recipients = [r for m in mail.outbox for r in m.to]
        self.assertIn(self.ctx['student'].email, recipients)
        self.assertIn(self.ctx['parent'].email, recipients)

    def test_resend_after_parent_email_corrected(self):
        """The whole point: bounce → admin updates parent email → resend → new address used."""
        # Simulate the bounce-and-correct flow
        parent = self.ctx['parent']
        parent.email = 'corrected_parent@example.com'
        parent.save(update_fields=['email'])

        mail.outbox = []
        result = svc.resend_invoice_email(self.ctx['invoice'])

        recipients = [r for m in mail.outbox for r in m.to]
        self.assertIn('corrected_parent@example.com', recipients)
        self.assertIn('corrected_parent@example.com', result['sent'])

    def test_resend_cancelled_invoice_raises(self):
        """Cancelled invoices cannot be resent."""
        invoice = self.ctx['invoice']
        invoice.status = 'cancelled'
        invoice.cancelled_at = timezone.now()
        invoice.save(update_fields=['status', 'cancelled_at'])

        with self.assertRaises(ValueError) as cm:
            svc.resend_invoice_email(invoice)
        self.assertIn('cancelled', str(cm.exception).lower())

    def test_resend_draft_invoice_raises(self):
        """Draft invoices cannot be resent — they were never emailed in the first place."""
        invoice = self.ctx['invoice']
        invoice.status = 'draft'
        invoice.issued_at = None
        invoice.save(update_fields=['status', 'issued_at'])

        with self.assertRaises(ValueError) as cm:
            svc.resend_invoice_email(invoice)
        self.assertIn('draft', str(cm.exception).lower())

    def test_resend_paid_invoice_still_works(self):
        """Resend remains available on paid invoices (admins may need to re-send a receipt-style copy)."""
        invoice = self.ctx['invoice']
        invoice.status = 'paid'
        invoice.save(update_fields=['status'])

        # Should not raise
        result = svc.resend_invoice_email(invoice)
        self.assertGreater(len(result['sent']), 0)

    def test_resend_when_student_has_no_email(self):
        """If student has no email, returns skipped_no_email=True (current early-return behavior)."""
        student = self.ctx['student']
        student.email = ''
        student.save(update_fields=['email'])

        result = svc.resend_invoice_email(self.ctx['invoice'])
        self.assertTrue(result['skipped_no_email'])
        self.assertEqual(result['sent'], [])

    def test_send_failure_is_recorded_in_failed_list(self):
        """If the email backend raises, the recipient is added to ``failed``."""
        with patch('classroom.email_service.send_templated_email',
                   side_effect=Exception('SMTP boom')):
            result = svc.resend_invoice_email(self.ctx['invoice'])

        # Both the student and the parent should appear under failed
        self.assertEqual(result['sent'], [])
        failed_lower = {e.lower() for e in result['failed']}
        self.assertIn(self.ctx['student'].email.lower(), failed_lower)
        self.assertIn(self.ctx['parent'].email.lower(), failed_lower)


# ---------------------------------------------------------------------------
# View-level tests (HTTP through Django test client)
# ---------------------------------------------------------------------------

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ResendInvoiceViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ctx = _build_school_with_invoice(name_suffix='_view')

    def setUp(self):
        mail.outbox = []
        self.client = Client()
        self.client.force_login(self.ctx['admin'])

    def _post_resend(self, invoice_id=None):
        invoice_id = invoice_id or self.ctx['invoice'].id
        return self.client.post(
            reverse('resend_invoice', kwargs={'invoice_id': invoice_id}),
            HTTP_REFERER=reverse('invoice_list'),
        )

    def test_post_resends_and_redirects_back_with_success(self):
        response = self._post_resend()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('invoice_list'))

        # The email was actually sent
        recipients = [r for m in mail.outbox for r in m.to]
        self.assertIn(self.ctx['student'].email, recipients)
        self.assertIn(self.ctx['parent'].email, recipients)

        # Success-style flash message
        msgs = [str(m) for m in self.client.session.get('_messages', [])] or [
            str(m) for m in
            __import__('django.contrib.messages', fromlist=['get_messages'])
            .get_messages(response.wsgi_request)
        ] if False else []
        # Pull messages off the response context via follow=True
        follow_resp = self.client.get(reverse('invoice_list'))
        rendered = follow_resp.content.decode('utf-8', errors='ignore')
        # The flash message includes the invoice number when successful
        self.assertIn(self.ctx['invoice'].invoice_number, rendered)

    def test_post_on_cancelled_invoice_returns_error_no_email(self):
        invoice = self.ctx['invoice']
        invoice.status = 'cancelled'
        invoice.cancelled_at = timezone.now()
        invoice.save(update_fields=['status', 'cancelled_at'])

        response = self._post_resend()

        self.assertEqual(response.status_code, 302)
        # No email queued
        self.assertEqual(mail.outbox, [])

    def test_post_on_draft_invoice_returns_error_no_email(self):
        invoice = self.ctx['invoice']
        invoice.status = 'draft'
        invoice.issued_at = None
        invoice.save(update_fields=['status', 'issued_at'])

        response = self._post_resend()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(mail.outbox, [])

    def test_post_unknown_invoice_returns_404(self):
        response = self.client.post(
            reverse('resend_invoice', kwargs={'invoice_id': 99999999}),
        )
        self.assertEqual(response.status_code, 404)

    def test_invoice_in_other_school_returns_404(self):
        """Scoping check: resending an invoice that belongs to a different school is a 404."""
        other = _build_school_with_invoice(name_suffix='_view_other')
        # The current admin (self.ctx['admin']) is logged in;
        # they should not be able to resend the OTHER school's invoice
        response = self.client.post(
            reverse('resend_invoice', kwargs={'invoice_id': other['invoice'].id}),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(mail.outbox, [])

    def test_audit_log_written(self):
        """Successful resend writes an ``invoice_resent`` audit event."""
        from audit.models import AuditLog
        before = AuditLog.objects.filter(action='invoice_resent').count()

        self._post_resend()

        after = AuditLog.objects.filter(action='invoice_resent').count()
        self.assertEqual(after, before + 1)

        ev = AuditLog.objects.filter(action='invoice_resent').latest('id')
        self.assertEqual(ev.detail['invoice_id'], self.ctx['invoice'].id)
        self.assertIn(self.ctx['student'].email, ev.detail['sent_to'])
