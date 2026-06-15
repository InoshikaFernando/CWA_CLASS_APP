"""UI tests for CPP-343 — invoice email send-status on the invoice list."""

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


def _issue(invoice):
    from django.utils import timezone
    invoice.status = 'issued'
    invoice.issued_at = timezone.now()
    invoice.save(update_fields=['status', 'issued_at'])


def _log(invoice, status, error=''):
    from classroom.models import EmailLog
    return EmailLog.objects.create(
        school=invoice.school, invoice=invoice,
        recipient_email='recipient@example.com',
        subject='Invoice', notification_type='invoice',
        status=status, error_message=error,
    )


class TestInvoiceListEmailStatus:
    """/invoicing/ Email column + ?email= filter."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, invoice):
        self.url = live_server.url
        self.page = page
        self.invoice = invoice
        do_login(page, self.url, hoi_user)

    def _goto_list(self, query=''):
        self.page.goto(f"{self.url}/invoicing/{query}")
        self.page.wait_for_load_state("domcontentloaded")

    def test_email_column_header_present(self):
        self._goto_list()
        assert_page_has_text(self.page, "Email")

    def test_email_filter_dropdown_present(self):
        self._goto_list()
        expect(self.page.locator("select[name='email']")).to_have_count(1)

    def test_sent_badge_shown(self):
        _issue(self.invoice)
        _log(self.invoice, 'sent')
        self._goto_list()
        body = self.page.locator("body").inner_text()
        assert "Sent" in body

    def test_failed_badge_shown(self):
        _issue(self.invoice)
        _log(self.invoice, 'failed', error='SMTP refused')
        self._goto_list()
        body = self.page.locator("body").inner_text()
        assert "Failed" in body

    def test_failed_filter_shows_failed_invoice(self):
        _issue(self.invoice)
        _log(self.invoice, 'failed', error='SMTP refused')
        self._goto_list("?email=failed")
        assert_page_has_text(self.page, self.invoice.invoice_number)

    def test_failed_filter_hides_sent_invoice(self):
        _issue(self.invoice)
        _log(self.invoice, 'sent')
        self._goto_list("?email=failed")
        body = self.page.locator("body").inner_text()
        # No failed invoices → empty-state copy, invoice number absent
        assert self.invoice.invoice_number not in body
