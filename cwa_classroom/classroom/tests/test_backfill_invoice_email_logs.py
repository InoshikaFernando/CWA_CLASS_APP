"""
Tests for backfill_invoice_email_logs — the one-off repair for invoice EmailLog
rows written without their invoice FK.

Those rows are the residue of the August 2026 incident: the emails were
delivered, but the queue drain recorded them with a null invoice, so the
invoicing dashboard reports "Not sent" for invoices that did reach the family.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import EmailLog, Invoice, School, SchoolStudent
from classroom.views_invoicing import (
    _annotate_invoice_email_state, _invoice_email_state,
)


def _user(username, email=None, role=None):
    user = CustomUser.objects.create_user(
        username=username, password='pass', email=email,
        profile_completed=True, must_change_password=False)
    if role:
        obj, _ = Role.objects.get_or_create(
            name=role, defaults={'display_name': role.title()})
        user.roles.add(obj)
    return user


class BackfillInvoiceEmailLogsTest(TestCase):
    def setUp(self):
        self.admin = _user('bf_admin', 'bf_admin@example.com', role='admin')
        self.school = School.objects.create(
            name='Maths Hub Melbourne Pty Ltd', slug='bf-hub',
            admin=self.admin, is_active=True, invoice_due_days=30)
        plan, _ = InstitutePlan.objects.get_or_create(
            slug='bf-plan', defaults={
                'name': 'Plan', 'price': Decimal('0.00'), 'class_limit': 100,
                'student_limit': 100, 'invoice_limit_yearly': 1000,
                'extra_invoice_rate': Decimal('0.00')})
        SchoolSubscription.objects.create(
            school=self.school, plan=plan, status=SchoolSubscription.STATUS_ACTIVE)
        self.student = _user('bf_student', 'bf_student@example.com')
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.invoice = Invoice.objects.create(
            school=self.school, student=self.student,
            invoice_number='INV-4-2026-1524',
            amount=Decimal('210.00'), calculated_amount=Decimal('210.00'),
            status='issued', issued_at=timezone.now(),
            due_date=timezone.now().date(),
            billing_period_start=timezone.now().date(),
            billing_period_end=timezone.now().date())

    def _log(self, subject=None, **kw):
        return EmailLog.objects.create(
            recipient_email=kw.pop('email', 'parent@example.com'),
            subject=subject or f'Invoice {self.invoice.invoice_number} — {self.school.name}',
            notification_type=kw.pop('notification_type', 'invoice'),
            status=kw.pop('status', 'sent'),
            **kw)

    def test_dry_run_reports_but_writes_nothing(self):
        log = self._log()

        call_command('backfill_invoice_email_logs')

        log.refresh_from_db()
        self.assertIsNone(log.invoice_id)
        self.assertIsNone(log.school_id)

    def test_apply_attaches_invoice_and_school(self):
        log = self._log()

        call_command('backfill_invoice_email_logs', '--apply')

        log.refresh_from_db()
        self.assertEqual(log.invoice_id, self.invoice.id)
        self.assertEqual(log.school_id, self.school.id)

    def test_dashboard_flips_from_not_sent_to_sent(self):
        """The whole point: the invoice stops claiming it was never emailed."""
        self._log()

        before = _annotate_invoice_email_state(
            Invoice.objects.filter(pk=self.invoice.pk)).first()
        self.assertEqual(_invoice_email_state(before), 'none')

        call_command('backfill_invoice_email_logs', '--apply')

        after = _annotate_invoice_email_state(
            Invoice.objects.filter(pk=self.invoice.pk)).first()
        self.assertEqual(_invoice_email_state(after), 'sent')

    def test_cancellation_subject_is_also_matched(self):
        log = self._log(
            subject=f'Invoice {self.invoice.invoice_number} Cancelled — {self.school.name}',
            notification_type='invoice_cancelled')

        call_command('backfill_invoice_email_logs', '--apply')

        log.refresh_from_db()
        self.assertEqual(log.invoice_id, self.invoice.id)

    def test_every_recipient_of_one_invoice_is_repaired(self):
        first = self._log(email='mum@example.com')
        second = self._log(email='dad@example.com')

        call_command('backfill_invoice_email_logs', '--apply')

        for log in (first, second):
            log.refresh_from_db()
            self.assertEqual(log.invoice_id, self.invoice.id)

    def test_already_attributed_rows_are_left_alone(self):
        other = Invoice.objects.create(
            school=self.school, student=self.student,
            invoice_number='INV-4-2026-9999',
            amount=Decimal('10.00'), calculated_amount=Decimal('10.00'),
            status='issued', issued_at=timezone.now(),
            due_date=timezone.now().date(),
            billing_period_start=timezone.now().date(),
            billing_period_end=timezone.now().date())
        # Subject says 1524 but the row is already linked to 9999 — a correct
        # existing link must never be overwritten from the subject.
        log = self._log(invoice=other, school=self.school)

        call_command('backfill_invoice_email_logs', '--apply')

        log.refresh_from_db()
        self.assertEqual(log.invoice_id, other.id)

    def test_unknown_invoice_number_is_skipped_not_crashed(self):
        log = self._log(subject='Invoice INV-4-2026-0000 — Gone School')

        call_command('backfill_invoice_email_logs', '--apply')

        log.refresh_from_db()
        self.assertIsNone(log.invoice_id)

    def test_non_invoice_notification_types_are_untouched(self):
        log = self._log(
            subject='Your password was changed',
            notification_type='password_changed')

        call_command('backfill_invoice_email_logs', '--apply')

        log.refresh_from_db()
        self.assertIsNone(log.invoice_id)

    def test_provider_message_id_is_not_invented(self):
        """Delivery state for these rows is unrecoverable; don't fake it."""
        log = self._log()

        call_command('backfill_invoice_email_logs', '--apply')

        log.refresh_from_db()
        self.assertEqual(log.provider_message_id, '')
        self.assertEqual(log.status, 'sent')

    def test_limit_caps_the_first_pass(self):
        for i in range(5):
            self._log(email=f'r{i}@example.com')

        call_command('backfill_invoice_email_logs', '--apply', '--limit', '2')

        self.assertEqual(
            EmailLog.objects.filter(invoice__isnull=False).count(), 2)
