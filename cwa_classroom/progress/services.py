"""Generate and deliver end-of-period progress reports (CPP-388).

The generator is deliberately boring and idempotent: it keys reports on
``(student, period_type, period_start)`` and tracks delivery with two nullable
timestamps, so the daily cron can run twice — or be re-run after a failure —
without a child getting the same notification a second time.

Delivery split, per the spec:

* in-app notification to the student and every linked parent, every period;
* email to the parents at **term end only**. A weekly email per child per week
  is how a school ends up in a spam folder.
"""

import logging

from django.urls import reverse
from django.utils import timezone

from progress import reports
from progress.models import PeriodReport
from progress.periods import TERM, label_for, student_school
from progress.reports import build_report_data

logger = logging.getLogger(__name__)

TERM_EMAIL_TEMPLATE = 'email/transactional/term_progress_report.html'
NOTIF_TYPE = 'progress_report'
EMAIL_NOTIFICATION_TYPE = 'progress_report_term'


def classrooms_for_period(period_type, school=None, classroom=None,
                          mode=None, reference=None, term=None):
    """The classes a run would cover — the first half of students_for_period.

    Split out so a caller can tell an empty result apart from an empty scope.
    "No class is switched on" and "the class is switched on but has nobody in
    it" both end as an empty plan, and a page that guesses between them sends
    people to change a setting that is already correct.
    """
    from progress import report_settings

    classrooms = report_settings.enabled_classrooms(
        period_type, school=school, mode=mode, reference=reference, term=term,
    )
    if classroom is not None:
        classrooms = [c for c in classrooms if c.id == classroom.id]
    return classrooms


def students_for_period(period_type, school=None, classroom=None,
                        mode=None, reference=None, term=None,
                        subscribed_only=False, classrooms=None):
    """Who to generate for, and which classes each of their reports covers.

    Reports are opt-in: this walks the classes that resolved to *on* for this
    period type (see ``progress.report_settings``) rather than every student in
    the database. A school that has configured nothing yields nothing, which is
    the whole point — installing the cron must not start mailing families about
    a feature they have not switched on.

    *mode* restricts to manual or automatic classes, and *reference* keeps only
    the automatic ones whose configured day actually lands on that date — which
    is what lets one generic daily tick serve every school with nobody
    configuring a cron per school.

    Returns ``{student: {'classroom_ids': [...], 'delivery': {...}}}``. A
    student in two enabled classes gets one report covering both; delivery
    flags are OR-ed across those classes, because a parent who is opted in
    anywhere should not be silently dropped by a stricter sibling class.

    *classrooms* lets a caller that has already resolved the enabled classes
    pass them in rather than having them walked twice. ``run_period`` does,
    because it needs the class list itself to work out which schools the run
    covers for the whole-school outreach (CPP-422).

    *subscribed_only* narrows the plan to students whose own subscription is
    live (``billing.selectors``). It sits here rather than in the caller so the
    preview page and the send that follows it cannot disagree about who is in
    scope — a preview filtered in the template would show one list and mail a
    different one.
    """
    from classroom.models import ClassStudent
    from progress import report_settings

    if classrooms is None:
        classrooms = classrooms_for_period(
            period_type, school=school, classroom=classroom, mode=mode,
            reference=reference, term=term,
        )
    if not classrooms:
        return {}

    settings_by_class = {c.id: report_settings.effective(c) for c in classrooms}

    memberships = (
        ClassStudent.objects
        .filter(
            classroom_id__in=[c.id for c in classrooms],
            is_active=True,
            student__is_active=True,
        )
        .select_related('student')
    )
    if subscribed_only:
        from billing.selectors import filter_subscribed
        memberships = filter_subscribed(memberships, path='student__subscription')

    # A class with no subject of its own is filed under its department's, so
    # mapping a department files its reports correctly from the next run — the
    # same resolution the report body is scoped by, so the two cannot disagree.
    subject_by_class = {}
    for c in classrooms:
        resolved_for_class = reports.resolved_subject(c)
        subject_by_class[c.id] = resolved_for_class.id if resolved_for_class else None

    plan = {}
    for membership in memberships:
        entry = plan.setdefault(membership.student, {
            'classroom_ids': [],
            # Classes grouped by the subject they teach. A student in two
            # coding classes gets ONE coding report covering both, not two —
            # the subject is the unit a family reads, not the timetable slot.
            'by_subject': {},
            'delivery': {field: False for field in report_settings.DELIVERY_FIELDS},
            'content': {},
        })
        entry['classroom_ids'].append(membership.classroom_id)
        subject_id = subject_by_class.get(membership.classroom_id)
        entry['by_subject'].setdefault(subject_id, []).append(
            membership.classroom_id,
        )

        resolved = settings_by_class[membership.classroom_id]
        for field in report_settings.DELIVERY_FIELDS:
            entry['delivery'][field] = entry['delivery'][field] or resolved[field]
        # Content is OR-ed per subject, for the same reason delivery is OR-ed:
        # if any class of this subject asks for a section, the subject's report
        # carries it rather than being cut down by a stricter sibling class.
        content = entry['content'].setdefault(
            subject_id,
            {field: False for field in report_settings.CONTENT_FIELDS},
        )
        for field in report_settings.CONTENT_FIELDS:
            content[field] = content[field] or resolved[field]
    return plan


class PartialWindowError(ValueError):
    """Raised when a run is asked to store a report for a window still open.

    A term report keys on ``(student, term, period_start)`` where
    *period_start* is the term's start date, so a row written mid-term IS the
    row the real end-of-term report needs: ``generate_report`` would find it
    and return it untouched, and ``notify_report`` and
    ``email_parents_term_report`` are both no-ops once stamped. The family
    would never receive the end-of-term report at all.

    Staff can review a running term as much as they like — the preview builds
    the snapshot and discards it (CPP-425). What they cannot do is send one,
    and this is the line that makes that structural rather than a habit.
    """


def generate_report(student, period_type, start, end, term=None, force=False,
                    cohort_cache=None, classroom_ids=None, school=None,
                    subject=None, content=None):
    """Create (or refresh) one student's report for one window.

    Returns ``(report, created)``. An existing report is left alone unless
    *force* is set, in which case only ``data`` is recomputed — the delivery
    timestamps stay put so a re-computation never re-notifies.

    Raises :class:`PartialWindowError` for a term that has not ended. See that
    class for why storing one would cost the family their real report.

    *cohort_cache* is passed straight through to the builder; ``run_period``
    supplies one for the whole run so a class's award figures are computed once
    rather than once per student in it.
    """
    # The school being generated FOR, not whichever one the student happens to
    # resolve to. A child enrolled at two institutes was stamped with the school
    # `student_school` picked from their most recent class membership, so a
    # report built for one institute could be labelled with the other — which
    # decides both the term email's branding and, through can_view_report, which
    # Head of Institute is allowed to open it.
    if school is None:
        school = term.school if term is not None else student_school(student)

    # Judged on the WINDOW, not on the wall clock: the command can legitimately
    # be run with --date to regenerate a term that closed months ago, and a
    # clock-based test would refuse the very reports it exists to produce. What
    # makes a term report partial is that its window stops short of the term's
    # end — which is exactly what a mid-term review does, and exactly what must
    # never be stored.
    if term is not None and term.end_date is not None and end < term.end_date:
        raise PartialWindowError(
            f'{term} runs to {term.end_date:%d %b %Y}, so a report covering '
            f'only up to {end:%d %b %Y} cannot be stored — it would take the '
            f'place of the real end-of-term report, which the family would '
            f'then never receive. Review it from Preview Reports instead.'
        )

    report = PeriodReport.objects.filter(
        student=student, period_type=period_type, period_start=start,
        subject=subject,
    ).first()
    if report is not None and not force:
        return report, False

    data = build_report_data(
        student, period_type, start, end, term=term, cohort_cache=cohort_cache,
        classroom_ids=classroom_ids, subject=subject, content=content,
    )

    if report is None:
        report = PeriodReport.objects.create(
            student=student, school=school, term=term, subject=subject,
            period_type=period_type, period_start=start, period_end=end,
            data=data,
        )
        return report, True

    report.data = data
    report.school = school
    report.term = term
    report.period_end = end
    report.save(update_fields=['data', 'school', 'term', 'period_end'])
    return report, False


def _report_url(report):
    return reverse('progress:period_report_detail', kwargs={'report_id': report.id})


def linked_parents(student):
    """Active parent accounts for a student."""
    from classroom.models import ParentStudent

    return [
        link.parent for link in
        ParentStudent.objects.filter(student=student, is_active=True)
        .select_related('parent')
        if link.parent.is_active
    ]


def notify_report(report, to_student=True, to_parents=True):
    """In-app notification to the student and their parents. Idempotent.

    *to_student* / *to_parents* come from the resolved school/department/class
    settings, so a school can run a silent trial — generate the reports, read
    the numbers, and only then let the families see them.

    Email is suppressed here on purpose (``send_email=False``): the only email
    this feature sends is the end-of-term one below.
    """
    from classroom.notifications import create_notification

    if report.notified_at is not None:
        return 0
    if not (to_student or to_parents):
        # Nothing was sent, so nothing is stamped: turning notifications on
        # later must still be able to notify this report.
        return 0
    if not report.has_activity:
        # A report with nothing in it still exists and is still viewable — but
        # "here is your report: nothing" every Monday is not motivating.
        return 0

    url = _report_url(report)
    student = report.student
    name = student.get_full_name() or student.username
    totals = report.totals
    period_label = report.label

    student_message = (
        f'Your {report.get_period_type_display().lower()} progress report for '
        f'{period_label} is ready — {totals.get("avg_best_pct", 0)}% average '
        f'across {totals.get("homework_attempted", 0)} homework.'
    )
    recipients = [(student, student_message)] if to_student else []

    parent_message = (
        f'{name}’s {report.get_period_type_display().lower()} progress '
        f'report for {period_label} is ready — '
        f'{totals.get("avg_best_pct", 0)}% average across '
        f'{totals.get("homework_attempted", 0)} homework.'
    )
    if to_parents:
        recipients += [(parent, parent_message) for parent in linked_parents(student)]
    if not recipients:
        return 0

    for user, message in recipients:
        create_notification(
            user=user, message=message,
            notification_type=NOTIF_TYPE, link=url, send_email=False,
        )

    report.notified_at = timezone.now()
    report.save(update_fields=['notified_at'])
    return len(recipients)


def email_parents_term_report(report):
    """End-of-term email to the parents. Term reports only, once each.

    Skipped for a term with no submissions, matching the in-app rule: an email
    reading "0% average across 0 homework" lands as a system error rather than
    as news, and a child who submitted nothing all term is a conversation for
    their teacher, not an automated mail-out. The report row still exists and is
    still viewable, and the school's own dashboards already show non-submission.

    Never raises: a bounced report email must not abort the nightly run for
    every student after this one.
    """
    from classroom.email_service import send_templated_email

    if report.period_type != TERM or report.parent_emailed_at is not None:
        return 0
    if not report.has_activity:
        return 0

    parents = [p for p in linked_parents(report.student) if p.email]
    if not parents:
        return 0

    student = report.student
    name = student.get_full_name() or student.username
    site_url = _site_url()
    context = {
        'student_name': name,
        'period_label': report.label,
        'totals': report.totals,
        'awards': report.awards,
        # The topic list is sorted weakest-first, so the head of it is where the
        # next bit of work is — which is what a parent can actually act on.
        'weak_topics': report.topics[:3],
        'report_url': f'{site_url}{_report_url(report)}',
        'pdf_url': f'{site_url}{reverse("progress:period_report_pdf", kwargs={"report_id": report.id})}',
    }

    sent = 0
    for parent in parents:
        try:
            ok = send_templated_email(
                recipient_email=parent.email,
                subject=f'[Wizards Learning Hub] {name} — {report.label} progress report',
                template_name=TERM_EMAIL_TEMPLATE,
                context=context,
                recipient_user=parent,
                notification_type=EMAIL_NOTIFICATION_TYPE,
                school=report.school,
            )
        except Exception:
            logger.exception(
                'Term progress report email failed for report %s → %s',
                report.id, parent.email,
            )
            ok = False
        sent += 1 if ok else 0

    # Stamped whether or not every send succeeded: the failures are in EmailLog
    # and the logger, and retrying the whole batch would re-mail the parents who
    # did receive it.
    report.parent_emailed_at = timezone.now()
    report.save(update_fields=['parent_emailed_at'])
    return sent


def _site_url():
    from django.conf import settings

    return getattr(settings, 'SITE_URL', '') or ''


def _student_classrooms_for_window(student, classroom_ids=None):
    """The classes a legacy report covered, for the CPP-395 backfill.

    Prefers the ids the snapshot recorded over today's memberships: a student
    who has since left a class was still in it when the report was written, and
    rebuilding from today's roster would silently drop that class's work.
    """
    from classroom.models import ClassRoom

    if classroom_ids:
        return list(reports.with_subject_sources(
            ClassRoom.objects.filter(id__in=classroom_ids)
        ).order_by('name'))
    return list(reports.with_subject_sources(
        ClassRoom.objects
        .filter(class_students__student=student, class_students__is_active=True)
    ).distinct().order_by('name'))


def _subjects_by_id(plan):
    """Load every Subject the plan touches in one query rather than per row."""
    from classroom.models import Subject

    ids = {
        subject_id
        for entry in plan.values()
        for subject_id in entry['by_subject']
        if subject_id is not None
    }
    return {s.id: s for s in Subject.objects.filter(id__in=ids)} if ids else {}


def run_period(period_type, start, end, term=None, *, force=False, dry_run=False,
               notify=True, school=None, classroom=None, mode=None,
               reference=None, subscribed_only=False):
    """Generate and deliver one window for every class that opted in.

    Returns a counts dict so the management command can report what actually
    happened rather than claiming success. ``classes`` being zero is the normal
    state for an install where nobody has configured anything yet, and is
    reported rather than passed over in silence.

    A school that has switched ``whole_school`` on (CPP-422) additionally has
    every one of its active students covered: those with nothing to show get a
    note to their parents saying why, rather than the silence that used to be
    indistinguishable from the school not bothering. See ``progress.outreach``.
    """
    if school is None and term is not None:
        school = term.school

    # Resolved here rather than inside the plan so the outreach below knows
    # which schools this run actually touched — a school with no enabled class
    # is not sending tonight, and whole-school coverage widens a send that is
    # happening rather than creating one that is not.
    classrooms = classrooms_for_period(
        period_type, school=school, classroom=classroom,
        mode=mode, reference=reference, term=term,
    )
    plan = students_for_period(
        period_type, school=school, classroom=classroom,
        mode=mode, reference=reference, term=term,
        subscribed_only=subscribed_only, classrooms=classrooms,
    )

    # One cohort cache for the whole run: classmates share a class, so without
    # it a class of 25 recomputes the same figures 25 times.
    cohort_cache = {}
    # {school_id: {student_id}} for the students this run has something to say
    # about — read by the whole-school outreach, which covers everyone else.
    with_activity = {}
    covered_classes = set()
    for entry in plan.values():
        covered_classes.update(entry['classroom_ids'])

    counts = {
        'period': label_for(period_type, start, end, term),
        'classes': len(covered_classes),
        'students': 0, 'generated': 0, 'refreshed': 0,
        'notified': 0, 'emailed': 0,
        # Whole-school outreach. Zero on a school that has not switched it on,
        # which is the default and is not an error.
        'notices': 0, 'notices_emailed': 0, 'notices_recipients': 0,
        'notices_undelivered': 0, 'notices_by_reason': {},
    }

    subjects = _subjects_by_id(plan)

    # Which school each enabled class belongs to, for the dry-run branch below.
    school_by_class = {room.id: room.school_id for room in classrooms}

    for student, entry in plan.items():
        counts['students'] += 1
        if dry_run:
            # A dry run does not build report data, so it cannot know who was
            # active. Treating every planned student as covered keeps the
            # outreach figure a FLOOR rather than a wild over-count: the
            # students it reports are the ones no enabled class holds at all,
            # and the command says so in as many words.
            for class_id in entry['classroom_ids']:
                school_id = school_by_class.get(class_id)
                if school_id:
                    with_activity.setdefault(school_id, set()).add(student.id)
            continue

        # One report per subject. A student taking maths and coding gets a
        # maths report and a coding report, each about its own subject.
        for subject_id, class_ids in sorted(
            entry['by_subject'].items(), key=lambda kv: (kv[0] is None, kv[0]),
        ):
            report, created = generate_report(
                student, period_type, start, end, term=term, force=force,
                cohort_cache=cohort_cache, classroom_ids=class_ids,
                school=school, subject=subjects.get(subject_id),
                content=entry['content'].get(subject_id),
            )
            counts['generated' if created else 'refreshed'] += 1

            if report.has_activity:
                # Who this run has something to say about. The outreach below
                # writes to everyone else in the school, so this set is what
                # keeps a family from getting a report AND a "nothing to show"
                # note in the same evening.
                with_activity.setdefault(report.school_id, set()).add(student.id)

            if not notify:
                continue

            delivery = entry['delivery']
            if notify_report(
                report,
                to_student=delivery['notify_student'],
                to_parents=delivery['notify_parents'],
            ):
                counts['notified'] += 1
            if period_type == TERM and delivery['email_parents_at_term']:
                counts['emailed'] += email_parents_term_report(report)

    _run_outreach(
        counts, classrooms, period_type, start, end,
        with_activity=with_activity, classroom=classroom,
        subscribed_only=subscribed_only, notify=notify, dry_run=dry_run,
    )
    return counts


def _run_outreach(counts, classrooms, period_type, start, end, *, with_activity,
                  classroom, subscribed_only, notify, dry_run):
    """Cover the rest of the school, for the schools that asked for it (CPP-422).

    Mutates *counts* in place, the way the rest of ``run_period`` accumulates.

    Skipped outright for two scopes, because in both the operator has already
    said who they mean and widening it would send to people they excluded on
    the screen in front of them:

    * a single-class run — "this class" is not "every student in the school";
    * a ``subscribed_only`` run — its whole purpose is to leave the
      unsubscribed out, and they are most of this cohort.
    """
    from progress import outreach, report_settings

    if classroom is not None or subscribed_only:
        return

    schools = {}
    for room in classrooms:
        if room.school_id and room.school_id not in schools:
            schools[room.school_id] = room.school

    for school_id, school_obj in sorted(schools.items()):
        flags = report_settings.outreach(school_obj)
        if not flags['whole_school']:
            continue
        result = outreach.run_notices(
            school_obj, period_type, start, end,
            students_with_activity=with_activity.get(school_id, set()),
            period_label=counts['period'],
            # --no-notify silences the whole run, this included: it exists so a
            # school can generate and read the numbers before a family sees
            # anything, and a note is something a family sees.
            email=flags['email_parents_no_data'] and notify,
            dry_run=dry_run,
        )
        counts['notices'] += result['cohort']
        counts['notices_emailed'] += result['emailed']
        counts['notices_recipients'] += result['recipients']
        counts['notices_undelivered'] += result['undelivered']
        for reason, number in result['by_reason'].items():
            counts['notices_by_reason'][reason] = (
                counts['notices_by_reason'].get(reason, 0) + number
            )
