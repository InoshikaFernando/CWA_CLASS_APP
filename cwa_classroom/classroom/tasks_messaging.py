"""
RQ background tasks for scheduled message dispatch (CPP-353).

Enqueue: django_rq.get_queue('default').enqueue(dispatch_message, msg_id)
Cron:    management command send_due_messages calls check_due_messages()
"""
import logging
from datetime import date, datetime, timedelta

import django_rq
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schedule computation
# ---------------------------------------------------------------------------

def compute_next_run_at(msg, from_dt=None):
    """Return the next aware datetime this message should fire, or None.

    - 'now'     → None (enqueued immediately, no future run)
    - 'once'    → msg.scheduled_at (the single fire time)
    - 'weekly'  → next occurrence of msg.send_day (0=Sun…6=Sat) at msg.send_time
    - 'monthly' → next occurrence of msg.send_day (1–28) at msg.send_time

    from_dt: treat as "now" for calculation (default: timezone.now()).
    Returns None if required fields are missing or msg is outside date range.
    """
    from django.utils import timezone as tz

    now = from_dt or tz.now()

    if msg.frequency == 'now':
        return None

    if msg.frequency == 'once':
        return msg.scheduled_at  # may be None if not set

    if msg.frequency in ('weekly', 'monthly') and not msg.send_time:
        return None

    if msg.frequency == 'weekly':
        if msg.send_day is None:
            return None
        # send_day: 0=Sun…6=Sat; Python weekday: 0=Mon…6=Sun
        target_py = (msg.send_day + 6) % 7
        days_ahead = (target_py - now.weekday()) % 7
        if days_ahead == 0:
            # Same weekday — check if time is still ahead today
            candidate = now.replace(
                hour=msg.send_time.hour, minute=msg.send_time.minute,
                second=0, microsecond=0,
            )
            if candidate <= now:
                days_ahead = 7
        target_date = (now + timedelta(days=days_ahead)).date()
        if not _in_range(target_date, msg):
            return None
        naive = datetime(
            target_date.year, target_date.month, target_date.day,
            msg.send_time.hour, msg.send_time.minute,
        )
        return tz.make_aware(naive)

    if msg.frequency == 'monthly':
        if msg.send_day is None:
            return None
        day = msg.send_day
        # Look up to 12 months ahead so send_day=31 survives consecutive short months
        # (e.g. Jan→Feb: both lack the 31st; March 31 is the correct next date).
        for delta_months in range(12):
            year, month = _add_months(now.year, now.month, delta_months)
            try:
                candidate_date = date(year, month, day)
            except ValueError:
                # day > days in month (e.g. day=31 in April)
                continue
            candidate = tz.make_aware(datetime(
                candidate_date.year, candidate_date.month, candidate_date.day,
                msg.send_time.hour, msg.send_time.minute,
            ))
            if candidate > now and _in_range(candidate_date, msg):
                return candidate
        return None


def _in_range(d, msg):
    """True if date d falls within msg.starts_at / msg.ends_at (inclusive, open ends ok)."""
    if msg.starts_at and d < msg.starts_at:
        return False
    if msg.ends_at and d > msg.ends_at:
        return False
    return True


def _add_months(year, month, delta):
    month += delta
    while month > 12:
        month -= 12
        year += 1
    return year, month


# ---------------------------------------------------------------------------
# RQ job
# ---------------------------------------------------------------------------

def dispatch_message(msg_id):
    """Send one ScheduledMessage and update its status.

    For recurring messages (weekly/monthly) the next_run_at is advanced and
    status returned to SCHEDULED so the cron picks it up again.
    For one-time or 'now' messages status becomes SENT (or FAILED on error).
    """
    from classroom.models import ScheduledMessage  # lazy to avoid circular import

    try:
        msg = ScheduledMessage.objects.get(pk=msg_id)
    except ScheduledMessage.DoesNotExist:
        logger.warning('dispatch_message: ScheduledMessage %s not found', msg_id)
        return

    # Guard against double-dispatch from overlapping cron ticks or manual re-enqueue.
    if msg.status != ScheduledMessage.STATUS_SCHEDULED:
        logger.info('dispatch_message: msg %s status=%s — skipping', msg_id, msg.status)
        return

    to_addrs  = [r['email'] for r in (msg.recipients_to  or []) if r.get('email')]
    cc_addrs  = [r['email'] for r in (msg.recipients_cc  or []) if r.get('email')]
    bcc_addrs = [r['email'] for r in (msg.recipients_bcc or []) if r.get('email')]

    if not to_addrs and not cc_addrs and not bcc_addrs:
        logger.warning('dispatch_message: no recipients for msg %s', msg_id)
        msg.status = ScheduledMessage.STATUS_FAILED
        msg.last_run_at = timezone.now()
        msg.save(update_fields=['status', 'last_run_at', 'updated_at'])
        return

    plain = strip_tags(msg.body_html) if msg.body_html else ''
    email = EmailMultiAlternatives(
        subject=msg.subject,
        body=plain,
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        to=to_addrs or cc_addrs,
        cc=cc_addrs if to_addrs else [],
        bcc=bcc_addrs,
    )
    if msg.body_html:
        email.attach_alternative(msg.body_html, 'text/html')

    now = timezone.now()
    try:
        email.send(fail_silently=False)
    except Exception as exc:
        logger.exception('dispatch_message: send failed for msg %s: %s', msg_id, exc)
        msg.status = ScheduledMessage.STATUS_FAILED
        msg.last_run_at = now
        msg.save(update_fields=['status', 'last_run_at', 'updated_at'])
        return

    msg.last_run_at = now

    if msg.frequency in ('weekly', 'monthly'):
        next_run = compute_next_run_at(msg, from_dt=now)
        if next_run:
            msg.next_run_at = next_run
            msg.status = ScheduledMessage.STATUS_SCHEDULED
        else:
            msg.next_run_at = None
            msg.status = ScheduledMessage.STATUS_SENT
    else:
        msg.next_run_at = None
        msg.status = ScheduledMessage.STATUS_SENT

    msg.save(update_fields=['status', 'next_run_at', 'last_run_at', 'updated_at'])
    logger.info('dispatch_message: sent msg %s (frequency=%s)', msg_id, msg.frequency)


# ---------------------------------------------------------------------------
# Cron checker
# ---------------------------------------------------------------------------

def check_due_messages():
    """Enqueue all SCHEDULED messages whose next_run_at is now or overdue.

    Called by the send_due_messages management command (cron every minute).
    Returns the count of jobs enqueued.

    Uses a stable job_id per message so overlapping cron invocations cannot
    enqueue the same message twice within the same dispatch cycle.
    """
    from classroom.models import ScheduledMessage  # lazy to avoid circular import

    now = timezone.now()
    due = list(ScheduledMessage.objects.filter(
        status=ScheduledMessage.STATUS_SCHEDULED,
        next_run_at__lte=now,
    ).values_list('id', flat=True))

    queue = django_rq.get_queue('default')
    count = 0
    for msg_id in due:
        queue.enqueue(dispatch_message, msg_id, job_id=f'dispatch-msg-{msg_id}')
        count += 1

    return count
