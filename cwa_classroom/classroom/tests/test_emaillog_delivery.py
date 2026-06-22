"""
Unit tests for EmailLog.apply_delivery_event (CPP-343).

The webhook drives an EmailLog through its delivery lifecycle. The model method
must: stamp each event's own timestamp, advance status only by precedence (so a
late 'opened' can't overwrite a terminal 'bounced'), and capture a bounce reason.
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from classroom.models import EmailLog


def _log(status='sent'):
    return EmailLog.objects.create(
        recipient_email='r@example.com', subject='Invoice',
        notification_type='invoice', status=status,
        provider_message_id='msg_1',
    )


class ApplyDeliveryEventTest(TestCase):

    def setUp(self):
        self.now = timezone.now()

    def test_delivered_advances_and_stamps(self):
        log = _log('sent')
        changed = log.apply_delivery_event('delivered', self.now)
        self.assertTrue(changed)
        self.assertEqual(log.status, 'delivered')
        self.assertEqual(log.delivered_at, self.now)
        self.assertEqual(log.status_updated_at, self.now)

    def test_opened_does_not_overwrite_bounced(self):
        # Terminal bounce, then a stray 'opened' arrives later.
        log = _log('sent')
        log.apply_delivery_event('bounced', self.now, reason='mailbox full')
        self.assertEqual(log.status, 'bounced')

        later = self.now + datetime.timedelta(minutes=5)
        changed = log.apply_delivery_event('opened', later)
        # Status stays bounced, but the opened_at timestamp is still recorded.
        self.assertEqual(log.status, 'bounced')
        self.assertEqual(log.opened_at, later)
        self.assertTrue(changed)  # opened_at was set

    def test_bounce_reason_captured_once(self):
        log = _log('sent')
        log.apply_delivery_event('bounced', self.now, reason='no such user')
        self.assertEqual(log.bounce_reason, 'no such user')
        # A second bounce event must not clobber the original reason.
        log.apply_delivery_event('bounced', self.now, reason='different')
        self.assertEqual(log.bounce_reason, 'no such user')

    def test_delayed_keeps_sent_but_does_not_regress_delivered(self):
        log = _log('sent')
        log.apply_delivery_event('delivered', self.now)
        # A delayed event ranks below delivered → status unchanged.
        changed = log.apply_delivery_event('delayed', self.now)
        self.assertEqual(log.status, 'delivered')
        self.assertFalse(changed)

    def test_clicked_advances_from_delivered(self):
        log = _log('sent')
        log.apply_delivery_event('delivered', self.now)
        later = self.now + datetime.timedelta(minutes=1)
        # clicked ranks below delivered, so status stays delivered, but the
        # clicked_at timestamp is recorded.
        changed = log.apply_delivery_event('clicked', later)
        self.assertEqual(log.clicked_at, later)
        self.assertEqual(log.status, 'delivered')
        self.assertTrue(changed)

    def test_no_change_returns_false(self):
        log = _log('delivered')
        log.delivered_at = self.now
        changed = log.apply_delivery_event('delivered', self.now)
        self.assertFalse(changed)
