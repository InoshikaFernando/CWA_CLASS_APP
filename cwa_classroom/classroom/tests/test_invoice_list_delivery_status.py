"""
Unit tests for CPP-343 delivery-aware email states on the invoice list.

Extends test_invoice_list_email_status with the webhook-driven states:
delivered / bounced (and the opened/clicked/delayed/complained statuses that
fold into them). The base sent/failed/none behaviour is covered there.
"""
import datetime

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.tests.test_invoice_email_logging import _build_full_context
from classroom.tests.test_invoice_list_email_status import _log


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestInvoiceListDeliveryStatus(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school, cls.student, cls.parent, cls.guardian, cls.invoice = (
            _build_full_context('delivstatus')
        )
        cls.now = timezone.now()

    def _state(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 200)
        by_num = {inv.invoice_number: inv for inv in resp.context['page']}
        return by_num[self.invoice.invoice_number].email_state

    def test_delivered(self):
        _log(self.invoice, self.school, 'delivered', self.now)
        self.assertEqual(self._state(), 'delivered')

    def test_opened_counts_as_delivered(self):
        _log(self.invoice, self.school, 'opened', self.now)
        self.assertEqual(self._state(), 'delivered')

    def test_clicked_counts_as_delivered(self):
        _log(self.invoice, self.school, 'clicked', self.now)
        self.assertEqual(self._state(), 'delivered')

    def test_delayed_is_sent_not_delivered(self):
        _log(self.invoice, self.school, 'delayed', self.now)
        self.assertEqual(self._state(), 'sent')

    def test_bounced(self):
        _log(self.invoice, self.school, 'bounced', self.now)
        self.assertEqual(self._state(), 'bounced')

    def test_complained_counts_as_bounced(self):
        _log(self.invoice, self.school, 'complained', self.now)
        self.assertEqual(self._state(), 'bounced')

    def test_bounce_then_resend_delivered_flips_to_delivered(self):
        _log(self.invoice, self.school, 'bounced', self.now - datetime.timedelta(hours=2))
        _log(self.invoice, self.school, 'delivered', self.now)
        self.assertEqual(self._state(), 'delivered')

    def test_delivered_then_later_bounce_flips_to_bounced(self):
        # e.g. a second recipient on a resend bounced after the first delivered.
        _log(self.invoice, self.school, 'delivered', self.now - datetime.timedelta(hours=2))
        _log(self.invoice, self.school, 'bounced', self.now)
        self.assertEqual(self._state(), 'bounced')
