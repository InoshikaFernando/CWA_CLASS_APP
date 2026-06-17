"""
Unit tests for the flag_undelivered_emails management command (CPP-343).

Reports emails accepted by Resend ('sent') that never advanced to a delivered
state within the grace window, while ignoring confirmed and recent ones.
"""
import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from classroom.models import EmailLog


def _log(status, age_minutes, message_id='msg'):
    log = EmailLog.objects.create(
        recipient_email='r@example.com', subject='Invoice',
        notification_type='invoice', status=status,
        provider_message_id=message_id,
    )
    when = timezone.now() - datetime.timedelta(minutes=age_minutes)
    EmailLog.objects.filter(pk=log.pk).update(sent_at=when)
    return log


class FlagUndeliveredEmailsTest(TestCase):

    def _run(self, **kwargs):
        out = StringIO()
        call_command('flag_undelivered_emails', stdout=out, **kwargs)
        return out.getvalue()

    def test_flags_stale_sent(self):
        _log('sent', age_minutes=30, message_id='stale')
        out = self._run()
        self.assertIn('stale', out)
        self.assertIn('1 email', out)

    def test_ignores_recent_sent(self):
        _log('sent', age_minutes=5, message_id='recent')
        out = self._run()
        self.assertIn('No unconfirmed', out)

    def test_ignores_delivered(self):
        _log('delivered', age_minutes=60, message_id='ok')
        out = self._run()
        self.assertIn('No unconfirmed', out)

    def test_ignores_rows_without_provider_id(self):
        log = _log('sent', age_minutes=60, message_id='')
        out = self._run()
        self.assertIn('No unconfirmed', out)

    def test_minutes_option(self):
        _log('sent', age_minutes=15, message_id='mid')
        # Default 20-min window: 15-min-old row is too recent.
        self.assertIn('No unconfirmed', self._run())
        # A 10-min window flags it.
        self.assertIn('mid', self._run(minutes=10))
