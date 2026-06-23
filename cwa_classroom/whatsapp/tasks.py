"""RQ task: deliver a queued WhatsApp message via the configured provider."""
import logging

from .models import WhatsAppMessageLog
from .providers import WhatsAppSendError, get_provider

logger = logging.getLogger(__name__)


def deliver_whatsapp_message(log_id):
    """Send one queued message. Re-raises retriable provider errors so RQ
    retries; marks the log failed on permanent errors. Idempotent: a log that
    is no longer ``queued`` (already sent, or terminal) is skipped."""
    try:
        log = WhatsAppMessageLog.objects.select_related('template').get(pk=log_id)
    except WhatsAppMessageLog.DoesNotExist:
        logger.warning('WhatsAppMessageLog %s not found; nothing to deliver', log_id)
        return

    if log.status != WhatsAppMessageLog.STATUS_QUEUED:
        logger.info('WhatsAppMessageLog %s already %s; skipping', log_id, log.status)
        return

    template = log.template
    if template is None or not template.is_active:
        log.mark_failed(code='template_inactive', detail='Template missing or inactive')
        return

    provider = get_provider()
    try:
        wamid = provider.send_template(
            to=log.recipient_phone,
            template_name=template.meta_template_name,
            language_code=template.language_code,
            params=log.template_params or [],
        )
    except WhatsAppSendError as exc:
        if exc.retriable:
            # Keep the log queued so RQ's Retry policy re-processes it on the
            # next attempt; just record the latest error. (If retries are
            # exhausted the job lands in RQ's failed registry and the log stays
            # queued for a reconcile/webhook sweep — Sprint 3.)
            log.error_code = exc.code
            log.error_detail = str(exc)
            log.save(update_fields=['error_code', 'error_detail'])
            raise
        log.mark_failed(code=exc.code, detail=str(exc))
        return

    log.mark_sent(provider_message_id=wamid)
    logger.info('WhatsApp message %s sent (wamid=%s)', log_id, wamid)
