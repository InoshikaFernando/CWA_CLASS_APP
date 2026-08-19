"""
Email queue health — one source of truth for "is mail actually going out?".

Consumed by the ops dashboard, the deep health endpoint, and the
check_email_queue_health alert command, so all three agree on what "stalled"
means rather than each re-deriving it.

Background: every invoice email is force-queued at issue time, so the
process_email_queue cron IS the delivery path. When that cron stopped in June
2026 the queue filled with 316 undelivered invoices for ten weeks and nothing
noticed — invoices showed as issued, and no surface reported the backlog. These
signals exist so that failure mode is visible within minutes, not months.
"""
from datetime import timedelta

from django.utils import timezone

# The drain runs every 2 minutes. A pending row older than this means it has
# missed many ticks, so the cron is stopped, broken, or pointed at the wrong
# checkout — all of which happened.
STALE_WARN_MINUTES = 30
STALE_CRIT_MINUTES = 240

# A backlog this deep is abnormal even if young: a large invoice batch drains in
# minutes under normal throughput.
DEPTH_WARN = 100

STATUS_OK = 'ok'
STATUS_WARNING = 'warning'
STATUS_CRITICAL = 'critical'


def get_email_queue_health(now=None):
    """Return a dict describing queue health. Never raises on empty data.

    Keys:
        status              'ok' | 'warning' | 'critical'
        reasons             list[str] — why it is not ok (empty when ok)
        pending             int  — rows waiting to be sent
        failed              int  — rows that gave up (unsent)
        sent_today          int  — emails delivered today (local time)
        oldest_pending_at   datetime | None
        oldest_pending_min  int | None — age of the oldest pending row
        last_sent_at        datetime | None — last successful delivery
        last_sent_min       int | None — minutes since that delivery
        pending_by_type     dict[str, int]
    """
    from .models import EmailQueue

    now = now or timezone.now()

    pending_qs = EmailQueue.objects.filter(status=EmailQueue.STATUS_PENDING)
    pending = pending_qs.count()
    failed = EmailQueue.objects.filter(
        status=EmailQueue.STATUS_FAILED, sent_at__isnull=True,
    ).count()

    oldest = pending_qs.order_by('created_at').values_list(
        'created_at', flat=True).first()
    last_sent = EmailQueue.objects.filter(
        status=EmailQueue.STATUS_SENT, sent_at__isnull=False,
    ).order_by('-sent_at').values_list('sent_at', flat=True).first()

    sent_today = EmailQueue.objects.filter(
        status=EmailQueue.STATUS_SENT,
        sent_at__date=timezone.localtime(now).date(),
    ).count()

    pending_by_type = {}
    for row in pending_qs.values('notification_type').distinct():
        kind = row['notification_type'] or '(none)'
        pending_by_type[kind] = pending_qs.filter(
            notification_type=row['notification_type']).count()

    oldest_min = int((now - oldest).total_seconds() // 60) if oldest else None
    last_sent_min = (
        int((now - last_sent).total_seconds() // 60) if last_sent else None
    )

    status = STATUS_OK
    reasons = []

    # Age is the real signal. Depth alone can be a legitimate big batch that is
    # about to drain; depth that is not moving is the problem.
    if oldest_min is not None:
        if oldest_min >= STALE_CRIT_MINUTES:
            status = STATUS_CRITICAL
            reasons.append(
                f'oldest queued email is {_humanise(oldest_min)} old — '
                f'the drain cron is not running'
            )
        elif oldest_min >= STALE_WARN_MINUTES:
            status = STATUS_WARNING
            reasons.append(
                f'oldest queued email is {_humanise(oldest_min)} old — '
                f'the drain is behind schedule'
            )

    if pending >= DEPTH_WARN and status == STATUS_OK:
        status = STATUS_WARNING
        reasons.append(f'{pending} emails waiting to be sent')

    if failed:
        if status == STATUS_OK:
            status = STATUS_WARNING
        reasons.append(f'{failed} email(s) gave up after repeated failures')

    return {
        'status': status,
        'reasons': reasons,
        'pending': pending,
        'failed': failed,
        'sent_today': sent_today,
        'oldest_pending_at': oldest,
        'oldest_pending_min': oldest_min,
        'last_sent_at': last_sent,
        'last_sent_min': last_sent_min,
        'pending_by_type': pending_by_type,
    }


def _humanise(minutes):
    """'45 minutes' / '3.2 hours' / '11 days' — readable at every scale."""
    if minutes < 60:
        return f'{minutes} minutes'
    if minutes < 60 * 48:
        return f'{minutes / 60:.1f} hours'
    return f'{minutes / 1440:.1f} days'
