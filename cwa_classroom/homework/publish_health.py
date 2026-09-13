"""
Scheduled-publish health — one source of truth for "is scheduled homework
actually reaching students?".

Consumed by the ops dashboard and the deep health endpoint, so both agree on
what "the publish cron is dead" means rather than each re-deriving it. Mirrors
``classroom.email_health`` and ``billing.subscription_health``.

Background: ``publish_scheduled_homework`` is the ONLY thing that sets
``published_at`` on a scheduled homework, and students gate on ``published_at``.
Every set the question-automation schedule builds (CPP-399) is created with a
*future* ``publish_at`` and NULL ``published_at`` on purpose — that gap is the
teacher's preview window — so the whole feature depends on that cron running
every five minutes.

The cron is a ``/etc/cron.d`` drop-in written by ``deploy/setup-app-prod.sh``,
which is a one-time provisioning script: ``scripts/deploy.sh`` never rewrites
it, so a droplet provisioned before the drop-in was added keeps running without
it. Nothing errors when that happens. The schedule generates the homework, the
teacher sees it in the preview window, the release time passes, and the class is
simply never sent anything — which is exactly how it was found, by a teacher
publishing a week's set by hand.

This module makes that state legible from inside the app, because the app is the
only surface that keeps running when the cron does not.
"""
from django.utils import timezone

# The publish cron runs every 5 minutes. A set still unpublished this long after
# its release time has missed several ticks, so the cron is stopped, broken, or
# installed in the wrong checkout — all of which have happened to this repo's
# other crons.
STALE_WARN_MINUTES = 15

# Past this the class has missed the release entirely — a lesson's homework that
# was due to land in the morning and still has not by the afternoon.
STALE_CRIT_MINUTES = 360

# Cap on the per-homework detail rows. The counts are always exact; only the
# listing is trimmed, so a backlog of hundreds cannot turn one dashboard render
# into hundreds of queries.
MAX_ROWS = 25

STATUS_OK = 'ok'
STATUS_WARNING = 'warning'
STATUS_CRITICAL = 'critical'


def get_scheduled_publish_health(now=None):
    """Return a dict describing scheduled-publish health. Never raises on empty data.

    Keys:
        status              'ok' | 'warning' | 'critical'
        reasons             list[str] — why it is not ok (empty when ok)
        overdue             int  — sets whose publish_at has passed, still unpublished
        from_schedule       int  — how many of those a question schedule built
        upcoming            int  — sets scheduled to publish later (healthy backlog)
        oldest_overdue_at   datetime | None
        oldest_overdue_min  int | None — how late the oldest one is
        last_published_at   datetime | None — last set the cron published
        last_published_min  int | None — minutes since that publish
        rows                list[dict] — up to MAX_ROWS overdue sets, oldest first
    """
    from .models import Homework, ScheduleWeek

    now = now or timezone.now()

    # ``objects`` (not ``all_objects``) on purpose: it hides soft-deleted rows,
    # and so does the publish command, so a deleted set can never be reported as
    # something the cron failed to publish.
    scheduled_qs = Homework.objects.filter(
        published_at__isnull=True, publish_at__isnull=False,
    )
    overdue_qs = scheduled_qs.filter(publish_at__lte=now).order_by('publish_at')

    overdue = overdue_qs.count()
    upcoming = scheduled_qs.filter(publish_at__gt=now).count()

    oldest = overdue_qs.values_list('publish_at', flat=True).first()
    oldest_min = (
        int((now - oldest).total_seconds() // 60) if oldest else None
    )

    # Restricted to rows that carried a publish_at: a "Publish now" click also
    # stamps published_at, and counting those would make a dead cron look alive.
    last_published = Homework.objects.filter(
        published_at__isnull=False, publish_at__isnull=False,
    ).order_by('-published_at').values_list('published_at', flat=True).first()
    last_published_min = (
        int((now - last_published).total_seconds() // 60)
        if last_published else None
    )

    rows = []
    listed = list(
        overdue_qs.select_related('classroom')[:MAX_ROWS]
    )
    # One query rather than one per row: ScheduleWeek.generated_homework has
    # related_name='+', so there is no reverse accessor to follow.
    from_schedule_ids = set(
        ScheduleWeek.objects.filter(
            generated_homework_id__in=[hw.pk for hw in listed],
        ).values_list('generated_homework_id', flat=True)
    )
    for hw in listed:
        rows.append({
            'id': hw.pk,
            'title': hw.title,
            'classroom': hw.classroom.name if hw.classroom_id else '',
            'publish_at': hw.publish_at,
            'overdue_min': int((now - hw.publish_at).total_seconds() // 60),
            'from_schedule': hw.pk in from_schedule_ids,
        })

    from_schedule = ScheduleWeek.objects.filter(
        generated_homework_id__in=overdue_qs.values('pk'),
    ).count()

    status = STATUS_OK
    reasons = []

    # Age is the signal, not depth: one set a minute past its release time is a
    # cron tick away from being fine, while any set hours past it means nothing
    # is publishing at all.
    if oldest_min is not None:
        if oldest_min >= STALE_CRIT_MINUTES:
            status = STATUS_CRITICAL
            reasons.append(
                f'{overdue} scheduled homework set(s) are unpublished, the '
                f'oldest {_humanise(oldest_min)} past its release time — the '
                f'publish_scheduled_homework cron is not running'
            )
        elif oldest_min >= STALE_WARN_MINUTES:
            status = STATUS_WARNING
            reasons.append(
                f'{overdue} scheduled homework set(s) are unpublished, the '
                f'oldest {_humanise(oldest_min)} past its release time — the '
                f'publish is behind schedule'
            )

    if status != STATUS_OK and from_schedule:
        reasons.append(
            f'{from_schedule} of them were built by a question schedule, so '
            f'those classes have been sent nothing at all'
        )

    return {
        'status': status,
        'reasons': reasons,
        'overdue': overdue,
        'from_schedule': from_schedule,
        'upcoming': upcoming,
        'oldest_overdue_at': oldest,
        'oldest_overdue_min': oldest_min,
        'last_published_at': last_published,
        'last_published_min': last_published_min,
        'rows': rows,
    }


def _humanise(minutes):
    """'45 minutes' / '3.2 hours' / '11 days' — readable at every scale."""
    if minutes < 60:
        return f'{minutes} minutes'
    if minutes < 60 * 48:
        return f'{minutes / 60:.1f} hours'
    return f'{minutes / 1440:.1f} days'
