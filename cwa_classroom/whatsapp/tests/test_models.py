from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from whatsapp.models import (
    WhatsAppMessageLog, WhatsAppPreference, WhatsAppTemplate,
)
from whatsapp.tests.helpers import make_user


class WhatsAppPreferenceTests(TestCase):
    def test_opt_in_sets_flags_and_phone(self):
        pref = WhatsAppPreference.objects.create(user=make_user())
        pref.opt_in(phone='+64211234567')
        pref.refresh_from_db()
        self.assertTrue(pref.opted_in)
        self.assertIsNotNone(pref.opted_in_at)
        self.assertIsNone(pref.opted_out_at)
        self.assertEqual(pref.phone, '+64211234567')

    def test_opt_out_clears_opt_in(self):
        pref = WhatsAppPreference.objects.create(user=make_user())
        pref.opt_in()
        pref.opt_out()
        pref.refresh_from_db()
        self.assertFalse(pref.opted_in)
        self.assertIsNotNone(pref.opted_out_at)


class WhatsAppMessageLogTests(TestCase):
    def _log(self, **kwargs):
        defaults = dict(
            recipient_phone='+64211234567',
            event_type=WhatsAppMessageLog.EVENT_HOMEWORK_PUBLISHED,
            idempotency_key=f'key-{WhatsAppMessageLog.objects.count()}',
        )
        defaults.update(kwargs)
        return WhatsAppMessageLog.objects.create(**defaults)

    def test_idempotency_key_unique(self):
        self._log(idempotency_key='dup')
        with self.assertRaises(IntegrityError):
            self._log(idempotency_key='dup')

    def test_mark_sent_advances_status_and_stamps(self):
        log = self._log()
        log.mark_sent(provider_message_id='wamid.123')
        log.refresh_from_db()
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_SENT)
        self.assertEqual(log.provider_message_id, 'wamid.123')
        self.assertIsNotNone(log.sent_at)

    def test_mark_failed_records_error(self):
        log = self._log()
        log.mark_failed(code='oops', detail='bad number')
        log.refresh_from_db()
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_FAILED)
        self.assertEqual(log.error_code, 'oops')
        self.assertIsNotNone(log.failed_at)

    def test_terminal_status_not_overwritten_by_lower_event(self):
        # A late lower-ranked event (e.g. 'delivered') must not clobber a
        # terminal 'failed' status — though its timestamp is still recorded,
        # matching the EmailLog precedence pattern.
        log = self._log()
        log.mark_failed(code='hard', detail='permanent')
        now = timezone.now()
        log.apply_delivery_event(WhatsAppMessageLog.STATUS_DELIVERED, now)
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_FAILED)

    def test_read_not_overwritten_by_late_failed(self):
        # 'read' is terminal: a late/out-of-order 'failed' must not downgrade a
        # message that was already read (it did deliver).
        log = self._log()
        now = timezone.now()
        log.apply_delivery_event(WhatsAppMessageLog.STATUS_READ, now)
        # The failed event's timestamp is still recorded, but status stays read.
        log.apply_delivery_event(WhatsAppMessageLog.STATUS_FAILED, now)
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_READ)

    def test_failed_not_overwritten_by_late_success(self):
        # 'failed' is terminal: a stray later 'delivered' must not flip it.
        log = self._log()
        now = timezone.now()
        log.mark_failed(code='hard', detail='permanent')
        log.apply_delivery_event(WhatsAppMessageLog.STATUS_DELIVERED, now)
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_FAILED)

    def test_read_advances_over_delivered(self):
        log = self._log()
        now = timezone.now()
        log.apply_delivery_event(WhatsAppMessageLog.STATUS_DELIVERED, now)
        changed = log.apply_delivery_event(WhatsAppMessageLog.STATUS_READ, now)
        self.assertTrue(changed)
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_READ)
        self.assertIsNotNone(log.delivered_at)
        self.assertIsNotNone(log.read_at)


class WhatsAppTemplateTests(TestCase):
    def test_defaults_inactive(self):
        t = WhatsAppTemplate.objects.create(
            key='x', meta_template_name='x')
        self.assertFalse(t.is_active)
        self.assertEqual(t.category, WhatsAppTemplate.CATEGORY_UTILITY)
