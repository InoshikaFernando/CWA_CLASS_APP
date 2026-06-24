from unittest.mock import patch

from django.test import TestCase

from whatsapp import services
from whatsapp.models import (
    WhatsAppConfig, WhatsAppMessageLog, WhatsAppTemplate,
)
from whatsapp.tests.helpers import make_school, make_user

PUBLISHED = WhatsAppMessageLog.EVENT_HOMEWORK_PUBLISHED


def _active_template(key='homework_published'):
    return WhatsAppTemplate.objects.create(
        key=key, meta_template_name=key, is_active=True)


class ConfigResolutionTests(TestCase):
    def test_global_config_autocreated_disabled(self):
        cfg = services.global_config()
        self.assertIsNone(cfg.school_id)
        self.assertFalse(bool(cfg.is_enabled))

    def test_disabled_by_default(self):
        school = make_school()
        self.assertFalse(services.is_enabled_for(school))

    def test_school_enabled_overrides_global_default(self):
        school = make_school()
        WhatsAppConfig.objects.create(school=school, is_enabled=True)
        self.assertTrue(services.is_enabled_for(school))

    def test_school_null_inherits_global_enabled(self):
        # Global flipped on; school has no row → inherits enabled.
        g = services.global_config()
        g.is_enabled = True
        g.save()
        school = make_school()
        self.assertTrue(services.is_enabled_for(school))

    def test_event_toggle_gated_by_enabled(self):
        school = make_school()
        WhatsAppConfig.objects.create(
            school=school, is_enabled=False, notify_on_publish=True)
        flags = services.config_for(school)
        self.assertFalse(flags['notify_on_publish'])

    def test_event_toggle_when_enabled(self):
        school = make_school()
        WhatsAppConfig.objects.create(
            school=school, is_enabled=True, notify_on_publish=False)
        flags = services.config_for(school)
        self.assertTrue(flags['enabled'])
        self.assertFalse(flags['notify_on_publish'])
        self.assertTrue(flags['notify_on_submission'])  # defaults True


class ActiveTemplateTests(TestCase):
    def test_returns_only_active(self):
        WhatsAppTemplate.objects.create(
            key='homework_published', meta_template_name='x', is_active=False)
        self.assertIsNone(services.active_template('homework_published'))
        WhatsAppTemplate.objects.filter(key='homework_published').update(
            is_active=True)
        self.assertIsNotNone(services.active_template('homework_published'))


class SendTemplateTests(TestCase):
    def setUp(self):
        self.school = make_school()
        WhatsAppConfig.objects.create(school=self.school, is_enabled=True)
        self.template = _active_template()

    def _send(self, **kwargs):
        defaults = dict(
            school=self.school, template_key='homework_published',
            params=['HW1', 'Class A', 'Fri'], event_type=PUBLISHED,
            phone='+64211234567', enqueue=False,
        )
        defaults.update(kwargs)
        return services.send_template(**defaults)

    def test_gated_out_when_disabled(self):
        WhatsAppConfig.objects.filter(school=self.school).update(is_enabled=False)
        self.assertIsNone(self._send())
        self.assertEqual(WhatsAppMessageLog.objects.count(), 0)

    def test_blocked_when_template_inactive(self):
        self.template.is_active = False
        self.template.save()
        self.assertIsNone(self._send())
        self.assertEqual(WhatsAppMessageLog.objects.count(), 0)

    def test_undeliverable_when_no_valid_phone(self):
        result = self._send(phone='not-a-number')
        self.assertIsNone(result)
        log = WhatsAppMessageLog.objects.get()
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_UNDELIVERABLE)
        self.assertEqual(log.error_code, 'no_phone')

    def test_happy_path_creates_queued_log_with_normalized_phone(self):
        log = self._send(phone='021 123 4567')
        self.assertIsNotNone(log)
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_QUEUED)
        self.assertEqual(log.recipient_phone, '+64211234567')
        self.assertEqual(log.template_params, ['HW1', 'Class A', 'Fri'])

    def test_recipient_phone_fallback(self):
        parent = make_user(phone='+64211234567')
        log = self._send(phone=None, recipient=parent)
        self.assertIsNotNone(log)
        self.assertEqual(log.recipient_phone, '+64211234567')
        self.assertEqual(log.recipient, parent)

    def test_idempotency_no_duplicate(self):
        first = self._send(idempotency_key='evt-1')
        second = self._send(idempotency_key='evt-1')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(WhatsAppMessageLog.objects.count(), 1)

    def test_enqueues_delivery_when_requested(self):
        with patch('whatsapp.services.enqueue_delivery') as mock_enqueue:
            log = self._send(enqueue=True)
            mock_enqueue.assert_called_once_with(log)

    def test_never_raises_into_caller(self):
        # An unexpected failure inside the send must be swallowed (comms must
        # not break the triggering action).
        with patch('whatsapp.services.normalize_msisdn',
                   side_effect=RuntimeError('boom')):
            self.assertIsNone(self._send())
