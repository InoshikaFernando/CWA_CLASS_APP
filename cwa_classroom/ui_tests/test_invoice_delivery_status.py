"""UI tests for CPP-343 — delivery status (delivered/bounced) on the invoice
list Email column and the invoice detail Email History panel."""

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


def _log(invoice, status, error='', bounce_reason=''):
    from django.utils import timezone
    from classroom.models import EmailLog
    return EmailLog.objects.create(
        school=invoice.school, invoice=invoice,
        recipient_email='recipient@example.com',
        subject='Invoice', notification_type='invoice',
        status=status, error_message=error,
        bounce_reason=bounce_reason, provider_message_id='msg_ui',
        status_updated_at=timezone.now(),
    )


class TestInvoiceDeliveryStatus:

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

    def _goto_detail(self):
        self.page.goto(f"{self.url}/invoicing/{self.invoice.id}/")
        self.page.wait_for_load_state("domcontentloaded")

    # -- list Email column --------------------------------------------------

    def test_delivered_badge_shown(self):
        _issue(self.invoice)
        _log(self.invoice, 'delivered')
        self._goto_list()
        assert "Delivered" in self.page.locator("body").inner_text()

    def test_bounced_badge_shown(self):
        _issue(self.invoice)
        _log(self.invoice, 'bounced', bounce_reason='mailbox full')
        self._goto_list()
        assert "Bounced" in self.page.locator("body").inner_text()

    def test_bounced_filter_includes_bounced_invoice(self):
        _issue(self.invoice)
        _log(self.invoice, 'bounced', bounce_reason='no such user')
        # Bounced folds into the 'failed' filter bucket.
        self._goto_list("?email=failed")
        assert_page_has_text(self.page, self.invoice.invoice_number)

    # -- detail Email History ----------------------------------------------

    def test_detail_shows_delivered_status(self):
        _issue(self.invoice)
        _log(self.invoice, 'delivered')
        self._goto_detail()
        assert "Delivered" in self.page.locator("body").inner_text()

    def test_detail_shows_bounce_reason(self):
        _issue(self.invoice)
        _log(self.invoice, 'bounced', bounce_reason='recipient rejected')
        self._goto_detail()
        body = self.page.locator("body").inner_text()
        assert "Bounced" in body
        assert "recipient rejected" in body
