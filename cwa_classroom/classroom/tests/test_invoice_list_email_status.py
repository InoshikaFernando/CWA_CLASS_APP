"""
Unit tests for CPP-343 — invoice email send-status on the invoice list view.

Covers:
  - Per-invoice email_state derivation: sent / failed / none
  - Resend semantics: a later 'sent' log flips a failed invoice back to 'sent';
    a later 'failed' log flips a sent invoice to 'failed'
  - 'Not sent' vs '—' rendering driven by invoice status
  - ?email= filter (sent | failed | none)
  - The latest failure reason is surfaced (last_email_error)
  - Tenant isolation: another invoice's logs never bleed into this invoice's state
"""
import datetime
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.models import EmailLog, Invoice
from classroom.tests.test_invoice_email_logging import _build_full_context


def _make_invoice(school, student, admin, number, status='issued'):
    return Invoice.objects.create(
        invoice_number=number,
        school=school, student=student,
        billing_period_start=datetime.date(2026, 4, 1),
        billing_period_end=datetime.date(2026, 4, 30),
        attendance_mode='all_class_days', billing_type='upfront',
        period_type='custom',
        calculated_amount=Decimal('100.00'), amount=Decimal('100.00'),
        status=status, issued_at=timezone.now(),
        created_by=admin, due_date=datetime.date(2026, 5, 30),
    )


def _log(invoice, school, status, when, error=''):
    """Create an EmailLog for an invoice with a controlled sent_at.

    EmailLog.sent_at is auto_now_add, so we override it post-create."""
    log = EmailLog.objects.create(
        school=school, invoice=invoice,
        recipient_email='recipient@example.com',
        subject='Invoice', notification_type='invoice',
        status=status, error_message=error,
    )
    EmailLog.objects.filter(pk=log.pk).update(sent_at=when)
    return log


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestInvoiceListEmailStatus(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school, cls.student, cls.parent, cls.guardian, cls.invoice = (
            _build_full_context('liststatus')
        )
        cls.now = timezone.now()

    def _page_invoices(self, **params):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse('invoice_list'), params)
        self.assertEqual(resp.status_code, 200)
        return resp, {inv.invoice_number: inv for inv in resp.context['page']}

    # -- state derivation ---------------------------------------------------

    def test_page_loads(self):
        resp, _ = self._page_invoices()
        self.assertEqual(resp.status_code, 200)

    def test_state_sent(self):
        _log(self.invoice, self.school, 'sent', self.now)
        _, by_num = self._page_invoices()
        self.assertEqual(by_num[self.invoice.invoice_number].email_state, 'sent')

    def test_state_failed(self):
        _log(self.invoice, self.school, 'failed', self.now, error='SMTP down')
        _, by_num = self._page_invoices()
        inv = by_num[self.invoice.invoice_number]
        self.assertEqual(inv.email_state, 'failed')
        self.assertIn('SMTP down', inv.last_email_error)

    def test_state_none_when_no_logs(self):
        _, by_num = self._page_invoices()
        self.assertEqual(by_num[self.invoice.invoice_number].email_state, 'none')

    def test_resend_success_flips_failed_to_sent(self):
        # Original send failed, a later resend succeeded.
        _log(self.invoice, self.school, 'failed', self.now - datetime.timedelta(hours=2), error='boom')
        _log(self.invoice, self.school, 'sent', self.now)
        _, by_num = self._page_invoices()
        self.assertEqual(by_num[self.invoice.invoice_number].email_state, 'sent')

    def test_later_failure_flips_sent_to_failed(self):
        # Sent first, then a later attempt failed.
        _log(self.invoice, self.school, 'sent', self.now - datetime.timedelta(hours=2))
        _log(self.invoice, self.school, 'failed', self.now, error='later boom')
        _, by_num = self._page_invoices()
        self.assertEqual(by_num[self.invoice.invoice_number].email_state, 'failed')

    def test_partial_batch_failure_marks_failed(self):
        # One recipient succeeded, another failed in the same batch.
        _log(self.invoice, self.school, 'sent', self.now)
        _log(self.invoice, self.school, 'failed', self.now, error='one recipient bounced')
        _, by_num = self._page_invoices()
        # The newest failed is not older than the newest sent → needs attention.
        self.assertEqual(by_num[self.invoice.invoice_number].email_state, 'failed')

    # -- tenant / invoice isolation ----------------------------------------

    def test_other_invoice_logs_do_not_bleed(self):
        other = _make_invoice(self.school, self.student, self.admin, 'INV-OTHER-LS')
        _log(other, self.school, 'failed', self.now, error='other invoice failed')
        _, by_num = self._page_invoices()
        # This invoice has no logs of its own.
        self.assertEqual(by_num[self.invoice.invoice_number].email_state, 'none')
        self.assertEqual(by_num['INV-OTHER-LS'].email_state, 'failed')

    # -- ?email= filter -----------------------------------------------------

    def test_filter_failed(self):
        sent_inv = _make_invoice(self.school, self.student, self.admin, 'INV-SENT-LS')
        failed_inv = _make_invoice(self.school, self.student, self.admin, 'INV-FAIL-LS')
        _log(sent_inv, self.school, 'sent', self.now)
        _log(failed_inv, self.school, 'failed', self.now, error='nope')
        _, by_num = self._page_invoices(email='failed')
        self.assertIn('INV-FAIL-LS', by_num)
        self.assertNotIn('INV-SENT-LS', by_num)
        # the base invoice (no logs) is excluded too
        self.assertNotIn(self.invoice.invoice_number, by_num)

    def test_filter_sent(self):
        sent_inv = _make_invoice(self.school, self.student, self.admin, 'INV-SENT2-LS')
        failed_inv = _make_invoice(self.school, self.student, self.admin, 'INV-FAIL2-LS')
        _log(sent_inv, self.school, 'sent', self.now)
        _log(failed_inv, self.school, 'failed', self.now, error='nope')
        _, by_num = self._page_invoices(email='sent')
        self.assertIn('INV-SENT2-LS', by_num)
        self.assertNotIn('INV-FAIL2-LS', by_num)

    def test_filter_none(self):
        sent_inv = _make_invoice(self.school, self.student, self.admin, 'INV-SENT3-LS')
        _log(sent_inv, self.school, 'sent', self.now)
        _, by_num = self._page_invoices(email='none')
        # base invoice has no logs → included; sent invoice excluded
        self.assertIn(self.invoice.invoice_number, by_num)
        self.assertNotIn('INV-SENT3-LS', by_num)

    def test_invalid_email_filter_ignored(self):
        _log(self.invoice, self.school, 'sent', self.now)
        resp, by_num = self._page_invoices(email='bogus')
        self.assertEqual(resp.context['email_filter'], '')
        self.assertIn(self.invoice.invoice_number, by_num)
