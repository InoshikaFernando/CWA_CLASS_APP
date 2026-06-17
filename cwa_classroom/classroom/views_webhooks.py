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

        Falls back to a plain JSON parse only when the ``svix`` package is not
        installed (keeps local/dev usable) — production must have it.
        """
        try:
            from svix.webhooks import Webhook, WebhookVerificationError
        except ImportError:  # pragma: no cover - svix is a prod dependency
            logger.error('svix is not installed; cannot verify Resend webhook signature.')
            try:
                return json.loads(request.body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return None

        # Svix needs the raw body plus the svix-* headers.
        headers = {
            'svix-id': request.headers.get('Svix-Id', ''),
            'svix-timestamp': request.headers.get('Svix-Timestamp', ''),
            'svix-signature': request.headers.get('Svix-Signature', ''),
        }
        try:
            return Webhook(secret).verify(request.body, headers)
        except WebhookVerificationError:
            logger.warning('Resend webhook signature verification failed.')
            return None
