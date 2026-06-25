"""
RQ background tasks for scheduled message dispatch (CPP-353).

Emails are now enqueued via the existing EmailQueue model so they benefit from
the project-wide daily-limit enforcement, retry logic, EmailLog tracking, and
the process_email_queue cron (runs every 2 min) — no Redis / RQ worker needed.
"""
import logging
import os
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schedule computation
# ---------------------------------------------------------------------------

def compute_next_run_at(msg, from_dt=None):
    """Return the next aware datetime this message should fire, or None.

    - 'now'     → None (dispatched immediately, no future run)
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
        for delta_months in range(12):
            year, month = _add_months(now.year, now.month, delta_months)
            try:
                candidate_date = date(year, month, day)
            except ValueError:
                continue
            candidate = tz.make_aware(datetime(
                candidate_date.year, candidate_date.month, candidate_date.day,
                msg.send_time.hour, msg.send_time.minute,
            ))
            if candidate > now and _in_range(candidate_date, msg):
                return candidate
        return None


def _in_range(d, msg):
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
# Dispatch — uses existing EmailQueue infrastructure
# ---------------------------------------------------------------------------

def dispatch_message(msg_id):
    """Enqueue one ScheduledMessage into EmailQueue and update its status.

    Uses the existing EmailQueue model so the project-wide process_email_queue
    cron (every 2 min) handles actual SMTP delivery, daily-limit enforcement,
    retry, and EmailLog tracking. No RQ worker or Redis required.

    For recurring messages (weekly/monthly) next_run_at is advanced and status
    returned to SCHEDULED so the cron picks it up again next time.
    """
    from classroom.models import ScheduledMessage  # lazy — avoid circular import
    from classroom.email_service import send_prebuilt_email

    try:
        with transaction.atomic():
            try:
                msg = ScheduledMessage.objects.select_for_update(skip_locked=True).get(
                    pk=msg_id, status=ScheduledMessage.STATUS_SCHEDULED
                )
            except ScheduledMessage.DoesNotExist:
                logger.info('dispatch_message: msg %s not found or not SCHEDULED (already dispatched?)', msg_id)
                return

            to_addrs  = [r['email'] for r in (msg.recipients_to  or []) if r.get('email')]
            cc_addrs  = [r['email'] for r in (msg.recipients_cc  or []) if r.get('email')]
            bcc_addrs = [r['email'] for r in (msg.recipients_bcc or []) if r.get('email')]

            all_recipients = (
                to_addrs
                + [e for e in cc_addrs  if e not in to_addrs]
                + [e for e in bcc_addrs if e not in to_addrs and e not in cc_addrs]
            )

            if not all_recipients:
                logger.warning('dispatch_message: no recipients for msg %s', msg_id)
                msg.status = ScheduledMessage.STATUS_FAILED
                msg.last_run_at = timezone.now()
                msg.save(update_fields=['status', 'last_run_at', 'updated_at'])
                return

            subject      = msg.subject or '(No subject)'
            html_content = msg.body_html or ''
            now          = timezone.now()
            school       = msg.school

            # Read attachment bytes once before the recipient loop (avoids re-reading
            # the file from storage for each recipient).
            att_data = []
            for att in msg.attachments.all():
                try:
                    with att.file.open('rb') as fh:
                        att_data.append((att.filename, fh.read()))
                except Exception:
                    logger.warning('dispatch_message: could not read attachment %s', att.filename)

            # Mark as sent (or rescheduled) inside the transaction before sending,
            # so a concurrent call sees the updated status immediately.
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
            msg.last_run_at = now
            msg.save(update_fields=['status', 'next_run_at', 'last_run_at', 'updated_at'])

    except Exception:
        logger.exception('dispatch_message: error locking/updating msg %s', msg_id)
        return

    # Send emails outside the transaction — SMTP calls should not hold a DB lock.
    sent = failed = 0
    for email in to_addrs:
        ok = send_prebuilt_email(email, subject, html_content, cc=cc_addrs, school=school, att_data=att_data)
        sent += ok; failed += not ok
    for email in cc_addrs:
        if email not in to_addrs:
            ok = send_prebuilt_email(email, subject, html_content, school=school, att_data=att_data)
            sent += ok; failed += not ok
    for email in bcc_addrs:
        if email not in to_addrs and email not in cc_addrs:
            ok = send_prebuilt_email(email, subject, html_content, school=school, att_data=att_data)
            sent += ok; failed += not ok

    logger.info('dispatch_message: sent=%d failed=%d for msg %s (frequency=%s)',
                sent, failed, msg_id, msg.frequency)


# ---------------------------------------------------------------------------
# Synchronous dispatcher (no worker needed — runs inline)
# ---------------------------------------------------------------------------

def dispatch_due_sync():
    """Find all due SCHEDULED messages and dispatch them synchronously.

    Called by the inbox view on each load so messages are sent without needing
    a running RQ worker. dispatch_message() guards against double-dispatch by
    checking status == SCHEDULED at the start.
    """
    from classroom.models import ScheduledMessage  # lazy to avoid circular import

    now = timezone.now()
    due_ids = list(
        ScheduledMessage.objects.filter(
            status=ScheduledMessage.STATUS_SCHEDULED,
            next_run_at__lte=now,
        ).values_list('id', flat=True)
    )
    for msg_id in due_ids:
        try:
            dispatch_message(msg_id)
        except Exception:
            logger.exception('dispatch_due_sync: error dispatching msg %s', msg_id)


# ---------------------------------------------------------------------------
# Cron checker (send_due_messages management command)
# ---------------------------------------------------------------------------

def check_due_messages():
    """Dispatch all SCHEDULED messages whose next_run_at is now or overdue.

    Called by the send_due_messages management command (cron every minute).
    Now calls dispatch_message() directly — no RQ worker required.
    Returns the count of messages dispatched.
    """
    from classroom.models import ScheduledMessage  # lazy to avoid circular import

    now = timezone.now()
    due_ids = list(ScheduledMessage.objects.filter(
        status=ScheduledMessage.STATUS_SCHEDULED,
        next_run_at__lte=now,
    ).values_list('id', flat=True))

    count = 0
    for msg_id in due_ids:
        try:
            dispatch_message(msg_id)
            count += 1
        except Exception:
            logger.exception('check_due_messages: error dispatching msg %s', msg_id)

    return count
