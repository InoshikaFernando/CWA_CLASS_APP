"""
Tests for process_email_queue — the delivery path for every invoice email.

Covers the two failures behind the August 2026 incident, where 316 invoice
emails sat undelivered for ten weeks:

  * the drain wrote an EmailLog with no school/invoice and no provider message
    id, so the invoicing dashboard showed "Not sent" for every issued invoice
    and Resend's delivery webhooks had nothing to correlate against;
  * a failed row was reset to pending on every run with no cap, so a dead
    address looped forever and could not be suppressed.

A backlog warning is also asserted: a stalled queue must announce itself.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom.management.commands.process_email_queue import MAX_ATTEMPTS
from classroom.models import (
    EmailLog, EmailQueue, Invoice, School, SchoolStudent,
)


def _user(username, email=None, role=None):
    user = CustomUser.objects.create_user(
        username=username, password='pass', email=email,
        profile_completed=True, must_change_password=False,
    )
    if role:
        obj, _ = Role.objects.get_or_create(
            name=role, defaults={'display_name': role.title()})
        user.roles.add(obj)
    return user


class EmailQueueDrainTest(TestCase):
    def setUp(self):
        self.admin = _user('eqd_admin', 'eqd_admin@example.com', role='admin')
        self.school = School.objects.create(
            name='Maths Hub', slug='eqd-hub', admin=self.admin, is_active=True,
            invoice_due_days=30, invoice_recipient_policy='parents_fallback_student',
        )
        plan, _ = InstitutePlan.objects.get_or_create(
            slug='eqd-plan', defaults={
                'name': 'Plan', 'price': Decimal('0.00'), 'class_limit': 100,
                'student_limit': 100, 'invoice_limit_yearly': 1000,
                'extra_invoice_rate': Decimal('0.00'),
            })
        SchoolSubscription.objects.create(
            school=self.school, plan=plan, status=SchoolSubscription.STATUS_ACTIVE)

        self.student = _user('eqd_student', 'student@example.com')
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.invoice = Invoice.objects.create(
            school=self.school, student=self.student,
            invoice_number='INV-4-2026-1524',
            amount=Decimal('210.00'), calculated_amount=Decimal('210.00'),
            status='issued', issued_at=timezone.now(),
            due_date=timezone.now().date(),
            billing_period_start=timezone.now().date(),
            billing_period_end=timezone.now().date(),
        )

    def _queue(self, **overrides):
        defaults = dict(
            recipient=self.student,
            recipient_email='student@example.com',
            subject=f'Invoice {self.invoice.invoice_number} — {self.school.name}',
            from_email='noreply@wizardslearninghub.co.nz',
            html_content='<p>invoice</p>',
            text_content='invoice',
            notification_type='invoice',
        )
        defaults.update(overrides)
        return EmailQueue.objects.create(**defaults)

    # -- attribution ------------------------------------------------------

    def test_drain_attributes_log_from_queue_fks(self):
        """A row carrying the FKs produces a fully attributed EmailLog."""
        self._queue(school=self.school, invoice=self.invoice)

        call_command('process_email_queue')

        log = EmailLog.objects.get()
        self.assertEqual(log.status, 'sent')
        self.assertEqual(log.invoice_id, self.invoice.id)
        self.assertEqual(log.school_id, self.school.id)

    def test_drain_attributes_legacy_row_by_subject(self):
        """A row queued before the FKs existed is still matched to its invoice.

        This is what repairs an existing backlog as it drains — without it every
        already-queued email would land unattributable all over again.
        """
        self._queue()  # no school, no invoice — a pre-migration row
        self.assertIsNone(EmailQueue.objects.get().invoice_id)

        call_command('process_email_queue')

        log = EmailLog.objects.get()
        self.assertEqual(log.invoice_id, self.invoice.id)
        self.assertEqual(log.school_id, self.school.id)

    def test_drained_invoice_shows_as_sent_on_the_dashboard(self):
        """End to end: after draining, the invoice list no longer says 'Not sent'."""
        from classroom.views_invoicing import (
            _annotate_invoice_email_state, _invoice_email_state,
        )
        self._queue(school=self.school, invoice=self.invoice)

        before = _annotate_invoice_email_state(
            Invoice.objects.filter(pk=self.invoice.pk)).first()
        self.assertEqual(_invoice_email_state(before), 'none')

        call_command('process_email_queue')

        after = _annotate_invoice_email_state(
            Invoice.objects.filter(pk=self.invoice.pk)).first()
        self.assertEqual(_invoice_email_state(after), 'sent')

    def test_unmatched_subject_does_not_invent_an_invoice(self):
        """A non-invoice email is left unattributed rather than mis-linked."""
        self._queue(subject='Your password was changed',
                    notification_type='password_changed')

        call_command('process_email_queue')

        log = EmailLog.objects.get()
        self.assertIsNone(log.invoice_id)

    # -- retry cap --------------------------------------------------------

    def test_failed_row_below_cap_is_retried(self):
        row = self._queue(status=EmailQueue.STATUS_FAILED,
                          attempts=MAX_ATTEMPTS - 1, error_message='boom')

        call_command('process_email_queue', '--dry-run')

        row.refresh_from_db()
        self.assertEqual(row.status, EmailQueue.STATUS_PENDING)

    def test_failed_row_at_cap_is_not_retried(self):
        """Without this cap a dead address loops on every run, forever."""
        row = self._queue(status=EmailQueue.STATUS_FAILED,
                          attempts=MAX_ATTEMPTS, error_message='hard bounce')

        for _ in range(3):
            call_command('process_email_queue', '--dry-run')
            row.refresh_from_db()
            self.assertEqual(row.status, EmailQueue.STATUS_FAILED)

    def test_attempts_increment_on_send(self):
        row = self._queue(school=self.school, invoice=self.invoice)

        call_command('process_email_queue')

        row.refresh_from_db()
        self.assertEqual(row.attempts, 1)
        self.assertIsNotNone(row.last_attempt_at)
        self.assertEqual(row.status, EmailQueue.STATUS_SENT)

    # -- stalled queue ----------------------------------------------------

    def test_stale_backlog_is_announced(self):
        """A queue that stopped draining must not drain silently."""
        row = self._queue(school=self.school, invoice=self.invoice)
        EmailQueue.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=10))

        with self.assertLogs('classroom.management.commands.process_email_queue',
                             level='WARNING') as captured:
            call_command('process_email_queue')

        self.assertTrue(
            any('not being drained on schedule' in line for line in captured.output),
            captured.output,
        )

    def test_limit_caps_a_single_run(self):
        for i in range(5):
            self._queue(recipient_email=f'r{i}@example.com',
                        school=self.school, invoice=self.invoice)

        call_command('process_email_queue', '--limit', '2')

        self.assertEqual(
            EmailQueue.objects.filter(status=EmailQueue.STATUS_SENT).count(), 2)
        self.assertEqual(
            EmailQueue.objects.filter(status=EmailQueue.STATUS_PENDING).count(), 3)
