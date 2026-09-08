"""
Unit tests for the Resend delivery webhook (CPP-343).

Verifies Svix signature handling and that each event type advances the matching
EmailLog. Signatures are generated with the same HMAC scheme Svix uses so the
view's real verification path is exercised (no mocking of verify()).
"""
import base64
import hashlib
import hmac
import json
import time

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.models import EmailLog

# A valid Svix-style secret: 'whsec_' + base64(key bytes).
_SECRET = 'whsec_' + base64.b64encode(b'cpp343-test-secret-key-bytes!!').decode()


def _sign(secret, msg_id, timestamp, body_bytes):
    key = base64.b64decode(secret.split('_', 1)[1])
    signed = f'{msg_id}.{timestamp}.{body_bytes.decode()}'.encode()
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return f'v1,{sig}'


@override_settings(RESEND_WEBHOOK_SECRET=_SECRET)
class ResendWebhookTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('resend_webhook')
        self.log = EmailLog.objects.create(
            recipient_email='r@example.com', subject='Invoice',
            notification_type='invoice', status='sent',
            provider_message_id='msg_abc',
        )

    def _post(self, payload, secret=_SECRET, msg_id='evt_1'):
        body = json.dumps(payload).encode()
        ts = str(int(time.time()))
        headers = {
            'HTTP_SVIX_ID': msg_id,
            'HTTP_SVIX_TIMESTAMP': ts,
            'HTTP_SVIX_SIGNATURE': _sign(secret, msg_id, ts, body),
        }
        return self.client.post(
            self.url, data=body, content_type='application/json', **headers,
        )

    def _event(self, event_type, message_id='msg_abc', **data):
        return {'type': event_type, 'data': {'email_id': message_id, **data}}

    # -- signature ----------------------------------------------------------

    def test_valid_signature_marks_delivered(self):
        resp = self._post(self._event('email.delivered'))
        self.assertEqual(resp.status_code, 200)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'delivered')
        self.assertIsNotNone(self.log.delivered_at)

    def test_bad_signature_rejected(self):
        bad = 'whsec_' + base64.b64encode(b'the-wrong-secret-key-bytes!!!').decode()
        resp = self._post(self._event('email.delivered'), secret=bad)
        self.assertEqual(resp.status_code, 400)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'sent')

    @override_settings(RESEND_WEBHOOK_SECRET='')
    def test_missing_secret_returns_503(self):
        resp = self._post(self._event('email.delivered'))
        self.assertEqual(resp.status_code, 503)

    # -- event mapping ------------------------------------------------------

    def test_bounced_records_reason(self):
        resp = self._post({
            'type': 'email.bounced',
            'data': {'email_id': 'msg_abc', 'bounce': {'message': 'mailbox full'}},
        })
        self.assertEqual(resp.status_code, 200)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'bounced')
        self.assertEqual(self.log.bounce_reason, 'mailbox full')

    def test_complained_marks_complained(self):
        resp = self._post(self._event('email.complained'))
        self.assertEqual(resp.status_code, 200)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'complained')

    def test_opened_does_not_overwrite_bounced(self):
        self._post(self._event('email.bounced', bounce={'message': 'x'}))
        self._post(self._event('email.opened'))
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'bounced')
        self.assertIsNotNone(self.log.opened_at)

    def test_untracked_event_acked_204(self):
        resp = self._post(self._event('email.sent'))
        self.assertEqual(resp.status_code, 204)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'sent')

    def test_unknown_message_id_acked_202(self):
        resp = self._post(self._event('email.delivered', message_id='msg_unknown'))
        self.assertEqual(resp.status_code, 202)

    def test_missing_message_id_acked_202(self):
        resp = self._post({'type': 'email.delivered', 'data': {}})
        self.assertEqual(resp.status_code, 202)

    def test_get_not_allowed(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)


class SvixReturnValueTests(TestCase):
    """The payload must not come from ``Webhook.verify()``'s return value.

    svix 1.x returns the decoded payload from verify(); 2.x verifies only and
    returns None. The view used to return that value straight through, so under
    2.x every correctly-signed webhook read as unsigned and got a 400 — real
    Resend traffic dropped, EmailLog statuses frozen, and nothing in the logs
    but "signature verification failed" on signatures that were in fact valid.

    Because requirements.txt allowed any 1.x-or-later, a deploy that changed no
    code at all was enough to trigger it.

    This pins the behaviour independently of which svix is installed.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse('resend_webhook')
        self.log = EmailLog.objects.create(
            recipient_email='pupil@example.com', subject='Report',
            notification_type='invoice', status='sent',
            provider_message_id='msg_svix',
        )

    @override_settings(RESEND_WEBHOOK_SECRET=_SECRET)
    def test_a_verify_that_returns_none_still_delivers_the_event(self):
        from unittest.mock import patch

        payload = {'type': 'email.delivered', 'data': {'email_id': 'msg_svix'}}
        body = json.dumps(payload).encode()
        ts = str(int(time.time()))

        # Exactly what svix 2.x does: verify passes, returns nothing.
        with patch('svix.webhooks.Webhook.verify', return_value=None):
            resp = self.client.post(
                self.url, data=body, content_type='application/json',
                HTTP_SVIX_ID='evt_svix', HTTP_SVIX_TIMESTAMP=ts,
                HTTP_SVIX_SIGNATURE=_sign(_SECRET, 'evt_svix', ts, body),
            )

        self.assertEqual(resp.status_code, 200)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'delivered')

    @override_settings(RESEND_WEBHOOK_SECRET=_SECRET)
    def test_a_failed_verification_is_still_rejected(self):
        # The mirror: relaxing the return-value check must not have relaxed the
        # signature check with it.
        from unittest.mock import patch

        from svix.webhooks import WebhookVerificationError

        body = json.dumps({'type': 'email.delivered',
                           'data': {'email_id': 'msg_svix'}}).encode()
        with patch('svix.webhooks.Webhook.verify',
                   side_effect=WebhookVerificationError('bad')):
            resp = self.client.post(
                self.url, data=body, content_type='application/json',
                HTTP_SVIX_ID='evt_svix', HTTP_SVIX_TIMESTAMP='1',
                HTTP_SVIX_SIGNATURE='v1,nope',
            )

        self.assertEqual(resp.status_code, 400)
        self.log.refresh_from_db()
        self.assertEqual(self.log.status, 'sent')
