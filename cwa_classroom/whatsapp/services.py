"""WhatsApp send orchestration.

Sprint 1 scope: config resolution (null-inheritance), the gate, and the core
``send_template`` primitive — gate -> normalize phone -> log (queued) -> enqueue
async delivery. Recipient resolution across a class, dedupe, and the homework
event hooks build on this in Sprint 2.
"""
import logging
import uuid

from django.db import IntegrityError

from .models import WhatsAppConfig, WhatsAppMessageLog, WhatsAppTemplate
from .phone import normalize_msisdn

logger = logging.getLogger(__name__)


# ── config resolution ──────────────────────────────────────────────────────

def global_config():
    """The single ``school=NULL`` config row, created disabled if absent."""
    cfg = WhatsAppConfig.objects.filter(school__isnull=True).first()
    if cfg is None:
        cfg = WhatsAppConfig.objects.create(school=None, is_enabled=False)
    return cfg


def _effective(school_value, global_value, hard_default):
    """Resolve a tri-state flag: school value wins, else global, else default."""
    if school_value is not None:
        return school_value
    if global_value is not None:
        return global_value
    return hard_default


def config_for(school):
    """Resolved flags for a school as a dict.

    ``enabled`` hard-defaults to False (inert). The per-event toggles default
    True but are only meaningful when the feature is enabled, so they're ANDed
    with ``enabled``.
    """
    g = global_config()
    school_cfg = None
    if school is not None:
        school_cfg = WhatsAppConfig.objects.filter(
            school=school, removed_at__isnull=True).first()

    def pick(attr, default):
        sv = getattr(school_cfg, attr) if school_cfg else None
        return _effective(sv, getattr(g, attr), default)

    enabled = bool(pick('is_enabled', False))
    return {
        'enabled': enabled,
        'notify_on_publish': enabled and bool(pick('notify_on_publish', True)),
        'notify_on_submission': enabled and bool(pick('notify_on_submission', True)),
    }


def is_enabled_for(school):
    return config_for(school)['enabled']


def active_template(key):
    """Return the active template for ``key``, or None if missing/unapproved."""
    return WhatsAppTemplate.objects.filter(key=key, is_active=True).first()


# ── send primitive ─────────────────────────────────────────────────────────

def _gen_key():
    return uuid.uuid4().hex


def send_template(*, school, template_key, params, event_type, recipient=None,
                  phone=None, related_homework=None, related_submission=None,
                  idempotency_key=None, enqueue=True):
    """Gate, normalize, log, and enqueue one template message.

    Returns the ``WhatsAppMessageLog`` (queued, or an existing row for the same
    idempotency key), or None when the send is gated out or the number is
    undeliverable (an ``undeliverable`` log row is written in the latter case).
    Never raises into the caller — comms must not break the triggering action.
    """
    try:
        # 1. school enablement gate
        if not is_enabled_for(school):
            return None

        # 2. template gate (must exist + be Meta-approved)
        template = active_template(template_key)
        if template is None:
            logger.warning(
                'WhatsApp template %s missing/inactive; skipping %s send',
                template_key, event_type)
            return None

        # 3. resolve + normalize the destination number
        raw_phone = phone or (getattr(recipient, 'phone', '') if recipient else '')
        msisdn = normalize_msisdn(raw_phone)
        key = idempotency_key or _gen_key()

        if not msisdn:
            WhatsAppMessageLog.objects.create(
                school=school, recipient=recipient, recipient_phone=raw_phone or '',
                template=template, template_params=list(params or []),
                event_type=event_type, related_homework=related_homework,
                related_submission=related_submission,
                status=WhatsAppMessageLog.STATUS_UNDELIVERABLE,
                error_code='no_phone',
                error_detail='No valid E.164 number could be resolved',
                idempotency_key=key,
            )
            return None

        # 4. idempotency — never message the same recipient twice for one event
        existing = WhatsAppMessageLog.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return existing

        # 5. queued log
        try:
            log = WhatsAppMessageLog.objects.create(
                school=school, recipient=recipient, recipient_phone=msisdn,
                template=template, template_params=list(params or []),
                event_type=event_type, related_homework=related_homework,
                related_submission=related_submission,
                status=WhatsAppMessageLog.STATUS_QUEUED, idempotency_key=key,
            )
        except IntegrityError:
            # Lost a race on the idempotency key — return the winner's row.
            return WhatsAppMessageLog.objects.filter(idempotency_key=key).first()

        # 6. async delivery
        if enqueue:
            enqueue_delivery(log)
        return log
    except Exception:
        logger.exception(
            'WhatsApp send_template failed (event=%s template=%s)',
            event_type, template_key)
        return None


def enqueue_delivery(log):
    """Enqueue the async delivery task with RQ retry.

    Per-message sends use a direct RQ enqueue (not taskqueue.BackgroundTask):
    delivery state already lives on the message log, and one BackgroundTask row
    per message would be far too heavy at class-wide fan-out volumes.
    """
    import django_rq
    from rq import Retry

    from .tasks import deliver_whatsapp_message

    queue = django_rq.get_queue('default')
    queue.enqueue(
        deliver_whatsapp_message, log.id,
        retry=Retry(max=3, interval=[60, 300, 900]),
    )
