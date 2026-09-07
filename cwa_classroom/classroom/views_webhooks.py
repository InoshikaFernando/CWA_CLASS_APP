"""
Inbound webhook endpoints.

Currently: Resend delivery webhooks. Resend signs every webhook with Svix, so
we verify the signature against ``RESEND_WEBHOOK_SECRET`` before trusting the
payload, then advance the matching ``EmailLog`` row through its delivery
lifecycle (delivered / bounced / complained / opened / clicked / delayed).

Configure the webhook in the Resend dashboard to POST to ``/webhooks/resend/``
and copy its signing secret into ``RESEND_WEBHOOK_SECRET``.
"""
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import EmailLog

logger = logging.getLogger(__name__)

# Resend event type -> EmailLog status. Events we don't track are ignored.
RESEND_EVENT_STATUS = {
    'email.delivered': 'delivered',
    'email.bounced': 'bounced',
    'email.complained': 'complained',
    'email.delivery_delayed': 'delayed',
    'email.opened': 'opened',
    'email.clicked': 'clicked',
}


@method_decorator(csrf_exempt, name='dispatch')
class ResendWebhookView(View):
    """Receive Resend delivery webhooks and update EmailLog delivery status."""

    def post(self, request):
        secret = getattr(settings, 'RESEND_WEBHOOK_SECRET', '')
        if not secret:
            logger.error('Resend webhook received but RESEND_WEBHOOK_SECRET is not set.')
            return HttpResponse(status=503)

        payload = self._verify(request, secret)
        if payload is None:
            return HttpResponseBadRequest('invalid signature')

        event_type = payload.get('type', '')
        new_status = RESEND_EVENT_STATUS.get(event_type)
        if not new_status:
            # Event we don't track (e.g. email.sent) — ack and move on.
            return HttpResponse(status=204)

        data = payload.get('data', {}) or {}
        message_id = data.get('email_id') or data.get('id') or ''
        if not message_id:
            logger.warning('Resend webhook %s missing email id.', event_type)
            return HttpResponse(status=202)

        log = EmailLog.objects.filter(provider_message_id=message_id).first()
        if log is None:
            # Unknown id (e.g. an email we didn't log, or another environment).
            # Ack with 202 so Resend stops retrying.
            return HttpResponse(status=202)

        reason = ''
        if new_status == 'bounced':
            bounce = data.get('bounce') or {}
            reason = bounce.get('message') or bounce.get('description') or ''

        changed = log.apply_delivery_event(new_status, timezone.now(), reason=reason)
        if changed:
            log.save(update_fields=[
                'status', 'delivered_at', 'opened_at', 'clicked_at',
                'bounced_at', 'complained_at', 'bounce_reason',
                'status_updated_at',
            ])

        return HttpResponse(status=200)

    @staticmethod
    def _verify(request, secret):
        """Verify the Svix signature and return the parsed payload, or None.

        The payload is parsed from the body here rather than taken from
        ``verify()``'s return value, because that return value is not stable
        across svix majors: 1.x returns the decoded payload, 2.x verifies only
        and returns None. Reading it as the payload made every valid webhook
        look unsigned — a 400 on real, correctly-signed traffic, which stopped
        EmailLog delivery statuses updating until the deploy that installed
        svix 2.0 was noticed. Verification is what svix is for; decoding JSON
        is not, so we do that part ourselves.
        """
        try:
            from svix.webhooks import Webhook, WebhookVerificationError
        except ImportError:  # pragma: no cover - svix is a prod dependency
            # Refuse rather than accept an unverified webhook. The old fallback
            # parsed the body and carried on, which meant an environment
            # missing svix accepted ANY unsigned POST to this endpoint — and it
            # hid the 2.0 breakage from local test runs, because a machine
            # without svix never exercised verification at all.
            logger.error('svix is not installed; refusing the Resend webhook.')
            return None

        # Svix needs the raw body plus the svix-* headers.
        headers = {
            'svix-id': request.headers.get('Svix-Id', ''),
            'svix-timestamp': request.headers.get('Svix-Timestamp', ''),
            'svix-signature': request.headers.get('Svix-Signature', ''),
        }
        try:
            Webhook(secret).verify(request.body, headers)
        except WebhookVerificationError:
            logger.warning('Resend webhook signature verification failed.')
            return None

        try:
            return json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            logger.warning('Resend webhook body was not valid JSON.')
            return None
