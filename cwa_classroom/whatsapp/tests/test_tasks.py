from unittest.mock import MagicMock, patch

from django.test import TestCase

from whatsapp.models import WhatsAppMessageLog, WhatsAppTemplate
from whatsapp.providers import WhatsAppSendError
from whatsapp.tasks import deliver_whatsapp_message


class DeliverWhatsAppMessageTests(TestCase):
    def setUp(self):
        self.template = WhatsAppTemplate.objects.create(
            key='homework_published', meta_template_name='homework_published',
            is_active=True)

    def _queued_log(self, **kwargs):
        defaults = dict(
            recipient_phone='+64211234567', template=self.template,
            template_params=['HW1', 'Class A', 'Fri'],
            event_type=WhatsAppMessageLog.EVENT_HOMEWORK_PUBLISHED,
            status=WhatsAppMessageLog.STATUS_QUEUED,
            idempotency_key=f'k{WhatsAppMessageLog.objects.count()}',
        )
        defaults.update(kwargs)
        return WhatsAppMessageLog.objects.create(**defaults)

    @patch('whatsapp.tasks.get_provider')
    def test_happy_path_marks_sent(self, mock_get_provider):
        provider = MagicMock()
        provider.send_template.return_value = 'wamid.ABC'
        mock_get_provider.return_value = provider

        log = self._queued_log()
        deliver_whatsapp_message(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_SENT)
        self.assertEqual(log.provider_message_id, 'wamid.ABC')
        provider.send_template.assert_called_once()
        kwargs = provider.send_template.call_args.kwargs
        self.assertEqual(kwargs['to'], '+64211234567')
        self.assertEqual(kwargs['params'], ['HW1', 'Class A', 'Fri'])

    @patch('whatsapp.tasks.get_provider')
    def test_permanent_error_marks_failed_no_raise(self, mock_get_provider):
        provider = MagicMock()
        provider.send_template.side_effect = WhatsAppSendError(
            'bad number', code='invalid_to', retriable=False)
        mock_get_provider.return_value = provider

        log = self._queued_log()
        deliver_whatsapp_message(log.id)  # must not raise

        log.refresh_from_db()
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_FAILED)
        self.assertEqual(log.error_code, 'invalid_to')

    @patch('whatsapp.tasks.get_provider')
    def test_retriable_error_reraises_and_stays_queued(self, mock_get_provider):
        provider = MagicMock()
        provider.send_template.side_effect = WhatsAppSendError(
            'rate limited', code='429', retriable=True)
        mock_get_provider.return_value = provider

        log = self._queued_log()
        with self.assertRaises(WhatsAppSendError):
            deliver_whatsapp_message(log.id)

        log.refresh_from_db()
        # Stays queued so RQ's retry re-processes it; error is recorded.
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_QUEUED)
        self.assertEqual(log.error_code, '429')

    @patch('whatsapp.tasks.get_provider')
    def test_skips_non_queued_log(self, mock_get_provider):
        log = self._queued_log(status=WhatsAppMessageLog.STATUS_SENT)
        deliver_whatsapp_message(log.id)
        mock_get_provider.assert_not_called()

    @patch('whatsapp.tasks.get_provider')
    def test_inactive_template_marks_failed(self, mock_get_provider):
        self.template.is_active = False
        self.template.save()
        log = self._queued_log()
        deliver_whatsapp_message(log.id)
        mock_get_provider.assert_not_called()
        log.refresh_from_db()
        self.assertEqual(log.status, WhatsAppMessageLog.STATUS_FAILED)

    def test_missing_log_is_noop(self):
        deliver_whatsapp_message(999999)  # must not raise
