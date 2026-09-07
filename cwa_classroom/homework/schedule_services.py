"""
homework/schedule_services.py
============================
The question-automation schedule (CPP-399): turn a teacher's weekly teaching
plan into ordinary ``Homework`` rows.

Kept out of the views so the nightly management command, the "Generate now"
button and the tests all drive exactly the same code — the bug this avoids is
the cron and the button diverging and only one of them honouring, say, the
repeat-avoidance window.

Everything subject-specific goes through ``classroom.subject_registry``, so
Maths and Coding (and any future subject that implements the homework contract)
share one path rather than being branched on by slug.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from classroom.notifications import create_notification
from classroom.subject_registry import get as get_plugin

from .models import Homework, HomeworkQuestion, QuestionSchedule, ScheduleWeek

logger = logging.getLogger(__name__)

#: A teaching week is Monday-anchored. Term dates, holiday ranges and the
#: teacher's mental model of "week 3" all line up on Mondays, and pinning it
#: means a schedule's week numbers do not shift if its start date is edited by
#: a day or two.
WEEK_LENGTH_DAYS = 7


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def resolve_period(schedule) -> tuple[date, date]:
    """Return the ``(start, end)`` dates a schedule's weeks span.

    ``year`` and ``term`` scopes read their dates off the linked record;
    ``custom`` uses whatever the teacher typed. A year/term scope with no
    linked record falls back to the stored dates rather than raising — the FKs
    are ``SET_NULL``, so deleting a term must not make its schedules unreadable.
    """
    if schedule.scope == QuestionSchedule.SCOPE_YEAR and schedule.academic_year_id:
        return schedule.academic_year.start_date, schedule.academic_year.end_date
    if schedule.scope == QuestionSchedule.SCOPE_TERM and schedule.term_id:
        return schedule.term.start_date, schedule.term.end_date
    return schedule.start_date, schedule.end_date


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ---------------------------------------------------------------------------
# Holidays
# ---------------------------------------------------------------------------

def _holiday_ranges(school, start: date, end: date):
    """School holidays overlapping the window, as ``(start, end, name)`` tuples."""
    from classroom.models import SchoolHoliday

    if school is None:
        return []
    return [
        (h.start_date, h.end_date, h.name)
        for h in SchoolHoliday.objects.filter(
            school=school, start_date__lte=end, end_date__gte=start,
        )
    ]


def _public_holidays(school, start: date, end: date):
    """Public holidays in the window, as ``{date: name}``."""
    from classroom.models import PublicHoliday

    if school is None:
        return {}
    return {
        h.date: h.name
        for h in PublicHoliday.objects.filter(
            school=school, date__gte=start, date__lte=end,
        )
    }


def week_skip_reason(week_start: date, week_end: date, release_day: date,
                     holiday_ranges, public_holidays, period_start: date,
                     period_end: date) -> str:
    """Why this week should be created inactive, or ``''`` if it should run.

    Checked against the *release* day rather than the whole week: a set that
    goes live on Monday is unaffected by a Friday-only public holiday, and
    marking that week dead would silently cost the class a homework.
    """
    if release_day < period_start or release_day > period_end:
        return 'Outside the schedule period'
    for h_start, h_end, name in holiday_ranges:
        if h_start <= release_day <= h_end:
            return f'School holiday: {name}'
        # A holiday covering the entire week is a break even if the release day
        # itself sits just outside it (e.g. a Sunday release before a Mon–Fri
        # break) — there is no teaching that week to set questions on.
        if h_start <= week_start and h_end >= week_end:
            return f'School holiday: {name}'
    if release_day in public_holidays:
        return f'Public holiday: {public_holidays[release_day]}'
    return ''


def release_date_for(week_start: date, release_weekday: int) -> date:
    return week_start + timedelta(days=release_weekday)


def release_datetime(week) -> datetime:
    """The aware datetime this week's set goes live."""
    schedule = week.schedule
    naive = datetime.combine(
        release_date_for(week.week_start_date, schedule.release_weekday),
        schedule.release_time,
    )
    return timezone.make_aware(naive, timezone.get_current_timezone())


def build_at(week) -> datetime:
    """When the generator should build this week's set — ``lead_days`` early.

    The gap between this and ``release_datetime`` is the teacher's preview
    window: the homework exists, is visible to teachers, and is invisible to
    students because ``published_at`` stays NULL until the existing
    ``publish_scheduled_homework`` cron reaches ``publish_at``.
    """
    return release_datetime(week) - timedelta(days=week.schedule.lead_days)


# ---------------------------------------------------------------------------
# Week building
# ---------------------------------------------------------------------------

@transaction.atomic
def build_weeks(schedule) -> dict:
    """Create/refresh the ``ScheduleWeek`` rows spanning a schedule's period.

    Idempotent and non-destructive: rows are matched on ``week_start_date``, so
    re-running after the teacher has filled in topics keeps every selection.
    Weeks that fall outside the (possibly edited) period are removed **only**
    when nothing has been generated for them — deleting a week that already
    produced a homework would orphan the audit trail linking the two.

    Returns ``{'created': n, 'updated': n, 'removed': n, 'skipped': n}``.
    """
    start, end = resolve_period(schedule)
    school = schedule.classroom.school
    holiday_ranges = _holiday_ranges(school, start, end)
    public_holidays = _public_holidays(school, start, end)

    existing = {w.week_start_date: w for w in schedule.weeks.all()}
    seen: set[date] = set()
    created = updated = removed = skipped = 0

    cursor = monday_of(start)
    number = 0
    while cursor <= end:
        week_end = cursor + timedelta(days=WEEK_LENGTH_DAYS - 1)
        release_day = release_date_for(cursor, schedule.release_weekday)
        number += 1
        seen.add(cursor)

        reason = week_skip_reason(
            cursor, week_end, release_day, holiday_ranges, public_holidays,
            start, end,
        )
        if reason:
            skipped += 1

        week = existing.get(cursor)
        if week is None:
            ScheduleWeek.objects.create(
                schedule=schedule,
                week_number=number,
                week_start_date=cursor,
                week_end_date=week_end,
                is_active=not reason,
                skip_reason=reason,
            )
            created += 1
        else:
            fields = []
            if week.week_number != number:
                week.week_number = number
                fields.append('week_number')
            if week.week_end_date != week_end:
                week.week_end_date = week_end
                fields.append('week_end_date')
            # The teacher owns is_active once they have touched the week: a
            # re-save of the schedule must never silently re-disable a week
            # they deliberately turned back on. Only the *reason* is refreshed,
            # and a week is auto-disabled only if it is still untouched
            # (pending, no topics chosen).
            if week.skip_reason != reason:
                week.skip_reason = reason
                fields.append('skip_reason')
                if (reason and not week.topic_ids
                        and week.generation_status == ScheduleWeek.STATUS_PENDING):
                    week.is_active = False
                    fields.append('is_active')
            if fields:
                week.save(update_fields=fields)
                updated += 1
        cursor += timedelta(days=WEEK_LENGTH_DAYS)

    # Two-step renumber: week_number is unique per schedule, so assigning the
    # final numbers directly can collide with a row that still holds the number
    # mid-shuffle. Offset every row out of range first, then bring them back.
    stale = [w for start_date, w in existing.items() if start_date not in seen]
    for week in stale:
        if week.generated_homework_id is None:
            week.delete()
            removed += 1

    _renumber(schedule)
    return {'created': created, 'updated': updated, 'removed': removed,
            'skipped': skipped}


def _renumber(schedule) -> None:
    """Make week numbers a gapless 1..N run in date order."""
    weeks = list(schedule.weeks.order_by('week_start_date'))
    if not weeks:
        return
    offset = max(w.week_number for w in weeks) + len(weeks) + 1
    for i, week in enumerate(weeks):
        ScheduleWeek.objects.filter(pk=week.pk).update(week_number=offset + i)
    for i, week in enumerate(weeks, start=1):
        ScheduleWeek.objects.filter(pk=week.pk).update(week_number=i)
        week.week_number = i


# ---------------------------------------------------------------------------
# Topic labels
# ---------------------------------------------------------------------------

def refresh_topic_labels(week) -> list[str]:
    """Recompute a week's denormalised topic labels from its ids.

    Ids the plugin no longer recognises keep whatever label was stored last,
    tagged as removed, rather than vanishing — a teacher looking at last term's
    plan should still see what was taught, and the generator reports the stale
    id separately.
    """
    plugin = get_plugin(week.schedule.subject_slug)
    known = plugin.topic_labels(week.topic_ids) if plugin else {}
    previous = dict(zip(week.topic_ids or [], week.topic_labels or []))
    labels = []
    for tid in week.topic_ids or []:
        if tid in known:
            labels.append(known[tid])
        else:
            old = previous.get(tid)
            labels.append(f'{old} (removed)' if old and '(removed)' not in old
                          else (old or f'Topic #{tid} (removed)'))
    return labels


def unresolved_topic_ids(week) -> list[int]:
    """Planned topic ids the plugin can no longer resolve."""
    plugin = get_plugin(week.schedule.subject_slug)
    known = plugin.topic_labels(week.topic_ids) if plugin else {}
    return [tid for tid in (week.topic_ids or []) if tid not in known]


# ---------------------------------------------------------------------------
# Question selection
# ---------------------------------------------------------------------------

def recent_content_ids(classroom, subject_slug, weeks_back: int, *, before=None) -> set:
    """Content ids this class has already been given in the last N weeks.

    Scoped to the class and the subject, and read off ``HomeworkQuestion`` so it
    counts hand-made homework too — a teacher who set Fractions manually on
    Monday should not have the scheduler hand the same questions back on Friday.
    """
    if not weeks_back:
        return set()
    cutoff = (before or timezone.now()) - timedelta(days=weeks_back * WEEK_LENGTH_DAYS)
    return set(
        HomeworkQuestion.objects.filter(
            homework__classroom=classroom,
            homework__deleted_at__isnull=True,
            subject_slug=subject_slug,
            homework__created_at__gte=cutoff,
        ).values_list('content_id', flat=True)
    )


@dataclass
class PickResult:
    content_ids: list = field(default_factory=list)
    recycled: int = 0

    def __bool__(self):
        return bool(self.content_ids)


def pick_items_for_week(week, *, now=None) -> PickResult:
    """Choose this week's content ids, avoiding recent repeats where it can.

    Two passes on purpose. The first excludes everything the class has had
    lately. If that leaves fewer than the wanted count — normal for a small
    school-authored bank, or a narrow subtopic — the second pass re-asks
    without the exclusion and tops the set up. A short set is worse than a
    repeated question, and silently shipping five questions where ten were
    asked for is exactly the kind of quiet degradation this codebase forbids;
    the recycling is recorded on the week instead.
    """
    schedule = week.schedule
    plugin = get_plugin(schedule.subject_slug)
    if plugin is None or not plugin.supports_homework:
        return PickResult()

    wanted = week.effective_num_questions
    question_type = schedule.question_type or None
    excluded = recent_content_ids(
        schedule.classroom, schedule.subject_slug,
        schedule.avoid_repeat_weeks, before=now,
    )

    fresh = plugin.pick_homework_items(
        schedule.classroom, week.topic_ids, wanted,
        question_type=question_type,
        exclude_content_ids=excluded or None,
    )
    if len(fresh) >= wanted or not excluded:
        return PickResult(content_ids=list(fresh))

    # Top up from the full pool, skipping what pass one already chose.
    everything = plugin.pick_homework_items(
        schedule.classroom, week.topic_ids, wanted,
        question_type=question_type,
    )
    combined = list(fresh)
    seen = set(combined)
    for cid in everything:
        if len(combined) >= wanted:
            break
        if cid not in seen:
            combined.append(cid)
            seen.add(cid)
    return PickResult(content_ids=combined, recycled=len(combined) - len(fresh))


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    week: ScheduleWeek
    status: str
    message: str = ''
    homework: Homework | None = None

    @property
    def created(self):
        return self.homework is not None


def due_weeks(now=None, *, schedule_id=None):
    """Weeks whose build time has arrived and which have not been built yet.

    Ordered oldest-first so a schedule that has been paused and resumed catches
    up in teaching order rather than at random.
    """
    now = now or timezone.now()
    qs = (
        ScheduleWeek.objects
        .filter(
            is_active=True,
            schedule__is_active=True,
            generated_homework__isnull=True,
        )
        .exclude(generation_status=ScheduleWeek.STATUS_GENERATED)
        .select_related('schedule', 'schedule__classroom', 'schedule__classroom__school')
        .order_by('schedule_id', 'week_number')
    )
    if schedule_id:
        qs = qs.filter(schedule_id=schedule_id)
    # build_at() needs the schedule's release time and lead days, so the window
    # is applied in Python. The candidate set is small — active, ungenerated
    # weeks of active schedules — so this never walks the whole table.
    return [w for w in qs if build_at(w) <= now]


def generate_week(week, *, now=None, force=False) -> GenerationResult:
    """Build one week's homework. Idempotent.

    ``generated_homework`` is the guard: a week that already points at a
    homework returns ``skipped`` without touching anything, so a double cron
    tick, a manual "Generate now" racing the nightly run, or a re-run after a
    partial failure can never give a class two sets for the same week.

    ``force`` lets the teacher build a week before its lead time (the
    "Generate now" button); it does **not** override the idempotency guard or
    the active flags.
    """
    now = now or timezone.now()
    schedule = week.schedule

    if week.generated_homework_id is not None:
        # A teacher who soft-deletes a bad auto-generated set should be able to
        # ask for a new one — otherwise that week is dead for the rest of the
        # term. But only on an explicit "Generate now": having the nightly run
        # resurrect it would undo a week the teacher deliberately cancelled.
        deleted = Homework.all_objects.filter(
            pk=week.generated_homework_id, deleted_at__isnull=False,
        ).exists()
        if not (deleted and force):
            return GenerationResult(
                week, ScheduleWeek.STATUS_SKIPPED,
                'Already generated — the set was deleted, use Generate now to '
                'replace it.' if deleted else 'Already generated.',
            )
        week.generated_homework = None
        week.save(update_fields=['generated_homework'])
    if not schedule.is_active:
        return GenerationResult(week, ScheduleWeek.STATUS_SKIPPED,
                                'Schedule is paused.')
    if not week.is_active:
        return GenerationResult(week, ScheduleWeek.STATUS_SKIPPED,
                                week.skip_reason or 'Week is inactive.')
    if not week.topic_ids:
        return GenerationResult(week, ScheduleWeek.STATUS_SKIPPED,
                                'No topics planned for this week.')
    if not force and build_at(week) > now:
        return GenerationResult(week, ScheduleWeek.STATUS_SKIPPED,
                                'Not due yet.')

    plugin = get_plugin(schedule.subject_slug)
    if plugin is None or not plugin.supports_homework:
        return _record_failure(
            week, ScheduleWeek.STATUS_ERROR,
            f'No homework-capable plugin registered for "{schedule.subject_slug}".',
        )

    stale = unresolved_topic_ids(week)
    picked = pick_items_for_week(week, now=now)

    if not picked:
        detail = 'No questions matched the planned topics for this class.'
        if stale:
            detail += (f' {len(stale)} planned topic(s) no longer exist '
                       f'(ids: {", ".join(str(i) for i in stale)}).')
        result = _record_failure(week, ScheduleWeek.STATUS_NO_CONTENT, detail)
        notify_no_content(week, detail)
        return result

    release_at = release_datetime(week)
    labels = refresh_topic_labels(week)
    notes = []
    if picked.recycled:
        notes.append(
            f'{picked.recycled} question(s) reused from the last '
            f'{schedule.avoid_repeat_weeks} weeks — the topic bank was too '
            f'small to fill the set with fresh questions.'
        )
    if stale:
        notes.append(f'{len(stale)} planned topic(s) no longer exist and were ignored.')

    with transaction.atomic():
        # Re-read under the lock: two workers reaching the same week
        # concurrently must not both get past the guard above.
        locked = ScheduleWeek.objects.select_for_update().get(pk=week.pk)
        if locked.generated_homework_id is not None:
            return GenerationResult(week, ScheduleWeek.STATUS_SKIPPED,
                                    'Already generated.')

        homework = Homework(
            classroom=schedule.classroom,
            created_by=schedule.created_by,
            title=_week_title(week, labels),
            description=_week_description(week, labels),
            homework_type='topic',
            subject_slug=schedule.subject_slug,
            num_questions=len(picked.content_ids),
            due_date=release_at + timedelta(days=schedule.due_days),
            max_attempts=schedule.max_attempts,
            # Future publish_at + NULL published_at is what keeps this hidden
            # from students until publish_scheduled_homework reaches it. Never
            # set published_at here: that would skip the preview window AND the
            # student notification.
            publish_at=release_at,
        )
        homework.save()
        plugin.save_homework_topics(homework, week.topic_ids)
        _save_questions(homework, picked.content_ids)

        week.generated_homework = homework
        week.generated_at = now
        week.generation_status = ScheduleWeek.STATUS_GENERATED
        week.generation_message = ' '.join(notes)
        week.topic_labels = labels
        week.save(update_fields=[
            'generated_homework', 'generated_at', 'generation_status',
            'generation_message', 'topic_labels',
        ])

    _log_generated(week, homework, picked)
    return GenerationResult(week, ScheduleWeek.STATUS_GENERATED,
                            ' '.join(notes), homework=homework)


def _save_questions(homework, content_ids) -> None:
    """Persist the chosen items as ``HomeworkQuestion`` rows.

    Mirrors ``homework.views._select_and_save_questions``: ``bulk_create``
    bypasses ``save()``, so ``subject_slug`` and ``content_id`` must be set
    explicitly or the ``(homework, subject_slug, content_id)`` unique key
    collides on ``content_id=0``.
    """
    from maths.models import Question

    legacy_fk = {}
    if homework.subject_slug == 'mathematics':
        legacy_fk = {q.pk: q for q in Question.objects.filter(pk__in=content_ids)}

    HomeworkQuestion.objects.bulk_create([
        HomeworkQuestion(
            homework=homework,
            question=legacy_fk.get(cid),
            subject_slug=homework.subject_slug,
            content_id=cid,
            order=i,
        )
        for i, cid in enumerate(content_ids)
    ])


def _week_title(week, labels) -> str:
    topics = ', '.join(labels[:2]) if labels else 'Weekly practice'
    if len(labels) > 2:
        topics += f' +{len(labels) - 2} more'
    return f'Week {week.week_number}: {topics}'[:200]


def _week_description(week, labels) -> str:
    parts = [
        f'Automatically set from the "{week.schedule.name}" plan '
        f'(week {week.week_number}, {week.week_start_date:%d %b %Y}).'
    ]
    if labels:
        parts.append('Topics: ' + ', '.join(labels) + '.')
    if week.notes:
        parts.append(week.notes)
    return ' '.join(parts)


def _record_failure(week, status, message) -> GenerationResult:
    week.generation_status = status
    week.generation_message = message
    week.generated_at = timezone.now()
    week.save(update_fields=['generation_status', 'generation_message', 'generated_at'])
    logger.warning(
        'Schedule week %s (%s) did not generate: %s',
        week.pk, week.schedule.name, message,
    )
    return GenerationResult(week, status, message)


def _log_generated(week, homework, picked) -> None:
    from audit.services import log_event

    log_event(
        user=week.schedule.created_by,
        school=week.schedule.classroom.school,
        category='data_change',
        action='scheduled_homework_generated',
        detail={
            'schedule_id': week.schedule_id,
            'schedule_name': week.schedule.name,
            'week_number': week.week_number,
            'week_start_date': str(week.week_start_date),
            'homework_id': homework.id,
            'classroom_id': week.schedule.classroom_id,
            'subject_slug': week.schedule.subject_slug,
            'num_questions': len(picked.content_ids),
            'recycled': picked.recycled,
            'publish_at': str(homework.publish_at),
            'due_date': str(homework.due_date),
        },
    )


# ---------------------------------------------------------------------------
# Teacher notification
# ---------------------------------------------------------------------------

def schedule_managers(schedule):
    """Users who should hear about a schedule that could not produce a set.

    The class's teachers, plus whoever created the plan — the creator may be a
    HoD who is not listed as a class teacher, and they are the person who chose
    the topics that came up empty.
    """
    from classroom.models import ClassTeacher

    users = {
        ct.teacher
        for ct in ClassTeacher.objects.filter(classroom=schedule.classroom)
                                      .select_related('teacher')
        if ct.teacher_id
    }
    if schedule.created_by_id:
        users.add(schedule.created_by)
    return users


def notify_no_content(week, detail) -> int:
    """Tell the teachers a planned week produced nothing.

    A schedule that quietly generates no homework is the worst outcome here:
    the class sits a week with nothing set and nobody finds out until a parent
    asks. So this is a loud, addressed notification, not a log line.
    """
    schedule = week.schedule
    link = reverse('homework:schedule_detail', kwargs={'schedule_id': schedule.pk})
    message = (
        f'No questions could be set for week {week.week_number} '
        f'({week.week_start_date:%d %b %Y}) of "{schedule.name}" in '
        f'{schedule.classroom.name}. {detail} '
        f'Nothing was assigned — please review the plan or add content.'
    )
    sent = 0
    for user in schedule_managers(schedule):
        create_notification(
            user=user,
            message=message,
            notification_type='general',
            link=link,
        )
        sent += 1
    return sent


# ---------------------------------------------------------------------------
# Copy to another class
# ---------------------------------------------------------------------------

@transaction.atomic
def copy_schedule(schedule, target_classroom, user, *, name=None):
    """Clone a plan onto another class, carrying the week-by-week topics.

    The new schedule gets its own fresh week rows built from its own period
    (the target class may sit in a different academic year), and the topic
    selections are then transferred **by week number** — "week 3 is Fractions"
    is the thing being reused, not the calendar date.

    Generation state is deliberately not copied: the new class has not been set
    any of this yet.
    """
    weeks_by_number = {
        w.week_number: w for w in schedule.weeks.all()
    }

    clone = QuestionSchedule.objects.create(
        classroom=target_classroom,
        subject_slug=schedule.subject_slug,
        name=name or _unique_copy_name(schedule, target_classroom),
        scope=schedule.scope,
        academic_year=(
            target_classroom.academic_year
            if schedule.scope == QuestionSchedule.SCOPE_YEAR
            and target_classroom.academic_year_id
            else schedule.academic_year
        ),
        term=schedule.term,
        start_date=schedule.start_date,
        end_date=schedule.end_date,
        release_weekday=schedule.release_weekday,
        release_time=schedule.release_time,
        due_days=schedule.due_days,
        lead_days=schedule.lead_days,
        num_questions=schedule.num_questions,
        question_type=schedule.question_type,
        max_attempts=schedule.max_attempts,
        avoid_repeat_weeks=schedule.avoid_repeat_weeks,
        is_active=False,  # the teacher reviews the copy before it starts running
        created_by=user,
    )
    build_weeks(clone)

    for week in clone.weeks.all():
        source = weeks_by_number.get(week.week_number)
        if source is None or not source.topic_ids:
            continue
        week.topic_ids = list(source.topic_ids)
        week.topic_labels = list(source.topic_labels or [])
        week.num_questions = source.num_questions
        week.notes = source.notes
        week.save(update_fields=['topic_ids', 'topic_labels', 'num_questions', 'notes'])

    return clone


def _unique_copy_name(schedule, target_classroom) -> str:
    """A name that will not trip the (class, subject, name) unique key."""
    base = schedule.name
    candidate = base
    n = 1
    while QuestionSchedule.objects.filter(
        classroom=target_classroom, subject_slug=schedule.subject_slug,
        name=candidate,
    ).exists():
        n += 1
        candidate = f'{base} ({n})'
    return candidate


# ---------------------------------------------------------------------------
# Batch entry point (used by the management command)
# ---------------------------------------------------------------------------

def run_due(now=None, *, schedule_id=None, dry_run=False) -> list[GenerationResult]:
    """Generate every week that is due. Returns one result per week considered."""
    now = now or timezone.now()
    results = []
    for week in due_weeks(now, schedule_id=schedule_id):
        if dry_run:
            picked = pick_items_for_week(week, now=now) if week.topic_ids else PickResult()
            results.append(GenerationResult(
                week,
                ScheduleWeek.STATUS_GENERATED if picked else ScheduleWeek.STATUS_NO_CONTENT,
                f'would create {len(picked.content_ids)} question(s)',
            ))
            continue
        try:
            results.append(generate_week(week, now=now))
        except Exception as exc:  # noqa: BLE001 — one bad week must not stop the run
            logger.exception('Schedule week %s failed to generate', week.pk)
            results.append(_record_failure(
                week, ScheduleWeek.STATUS_ERROR, f'{type(exc).__name__}: {exc}',
            ))
    return results


# ---------------------------------------------------------------------------
# Coverage — "will this week's topics actually fill the set?"
# ---------------------------------------------------------------------------

@dataclass
class Coverage:
    """What a set of topics can supply against what a week asks for.

    ``total`` is everything the class could draw from those topics; ``fresh``
    is what is left after removing anything the class has had inside the
    schedule's repeat window. ``wanted`` is the week's question count.

    ``selected`` exists to keep "nothing chosen yet" apart from "chosen, and
    there is nothing there". Both have a total of zero, but the first is a
    week the teacher has not reached and the second is a fault they must act
    on — colouring them the same trains people to ignore the warning.
    """
    wanted: int = 0
    total: int = 0
    fresh: int = 0
    selected: int = 0

    @property
    def short_by(self) -> int:
        """How many questions the set would be missing entirely."""
        return max(0, self.wanted - self.total)

    @property
    def repeats(self) -> int:
        """How many of the set would have to be questions used recently."""
        if self.total <= 0:
            return 0
        return max(0, min(self.wanted, self.total) - self.fresh)

    @property
    def status(self) -> str:
        """``unplanned`` / ``none`` / ``short`` / ``repeats`` / ``ok``.

        Drives the colour: only ``short`` and ``none`` are faults.
        """
        if not self.selected:
            return 'unplanned'
        if self.total <= 0:
            return 'none'
        if self.short_by:
            return 'short'
        if self.repeats:
            return 'repeats'
        return 'ok'

    @property
    def message(self) -> str:
        if not self.selected:
            return 'No topics selected yet.'
        if self.total <= 0:
            return 'No questions available for these topics.'
        if self.short_by:
            return (
                f'Only {self.total} question{"" if self.total == 1 else "s"} '
                f'available — {self.short_by} short of the {self.wanted} asked for.'
            )
        if self.repeats:
            return (
                f'{self.fresh} unused question{"" if self.fresh == 1 else "s"} '
                f'available — {self.repeats} of the {self.wanted} would repeat '
                f'one the class has had recently.'
            )
        return f'{self.fresh} unused questions available for a set of {self.wanted}.'


def topic_counts_for_schedule(schedule, topic_ids, *, now=None):
    """``(total_by_topic, fresh_by_topic)`` for a schedule's whole topic tree.

    Two plugin calls for the entire page rather than one per week: a year-long
    plan is 40+ weeks over the same topic tree, and counting per week would
    issue the same query dozens of times.
    """
    plugin = get_plugin(schedule.subject_slug)
    if plugin is None or not topic_ids:
        return {}, {}

    question_type = schedule.question_type or None
    total = plugin.topic_content_counts(
        schedule.classroom, topic_ids, question_type=question_type,
    )
    recent = recent_content_ids(
        schedule.classroom, schedule.subject_slug,
        schedule.avoid_repeat_weeks, before=now,
    )
    if not recent:
        return total, dict(total)
    fresh = plugin.topic_content_counts(
        schedule.classroom, topic_ids, question_type=question_type,
        exclude_content_ids=recent,
    )
    # A topic whose every question is spent drops out of the grouped count, so
    # it must read as 0 rather than inherit its total.
    return total, {tid: fresh.get(tid, 0) for tid in total}


def coverage_for(week, total_by_topic, fresh_by_topic) -> Coverage:
    """Summarise one week's planned topics against its question count.

    Summing per-topic counts is sound because an item belongs to exactly one
    topic in both subjects (see ``SubjectPlugin.topic_content_counts``).
    """
    ids = week.topic_ids or []
    return Coverage(
        wanted=week.effective_num_questions,
        total=sum(total_by_topic.get(tid, 0) for tid in ids),
        fresh=sum(fresh_by_topic.get(tid, 0) for tid in ids),
        selected=len(ids),
    )
