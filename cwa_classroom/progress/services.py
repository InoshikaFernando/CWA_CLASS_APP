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

from progress.models import PeriodReport
from progress.periods import TERM, label_for, student_school
from progress.reports import build_report_data

logger = logging.getLogger(__name__)

TERM_EMAIL_TEMPLATE = 'email/transactional/term_progress_report.html'
NOTIF_TYPE = 'progress_report'
EMAIL_NOTIFICATION_TYPE = 'progress_report_term'


def eligible_students(school=None):
    """Active students to generate for.

    Scoped to users holding the student role. An inactive account is skipped —
    generating a report nobody can log in to read is churn, not coverage.
    """
    from accounts.models import CustomUser, Role

    qs = CustomUser.objects.filter(
        is_active=True,
        user_roles__role__name__in=[Role.STUDENT, Role.INDIVIDUAL_STUDENT],
    ).distinct()
    if school is not None:
        qs = qs.filter(
            class_student_entries__is_active=True,
            class_student_entries__classroom__school=school,
        ).distinct()
    return qs.order_by('id')


def generate_report(student, period_type, start, end, term=None, force=False,
                    cohort_cache=None):
    """Create (or refresh) one student's report for one window.

    Returns ``(report, created)``. An existing report is left alone unless
    *force* is set, in which case only ``data`` is recomputed — the delivery
    timestamps stay put so a re-computation never re-notifies.

    *cohort_cache* is passed straight through to the builder; ``run_period``
    supplies one for the whole run so a class's award figures are computed once
    rather than once per student in it.
    """
    school = term.school if term is not None else student_school(student)

    report = PeriodReport.objects.filter(
        student=student, period_type=period_type, period_start=start,
    ).first()
    if report is not None and not force:
        return report, False

    data = build_report_data(
        student, period_type, start, end, term=term, cohort_cache=cohort_cache,
    )

    if report is None:
        report = PeriodReport.objects.create(
            student=student, school=school, term=term,
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


def notify_report(report):
    """In-app notification to the student and their parents. Idempotent.

    Email is suppressed here on purpose (``send_email=False``): the only email
    this feature sends is the end-of-term one below.
    """
    from classroom.notifications import create_notification

    if report.notified_at is not None:
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
    recipients = [(student, student_message)]

    parent_message = (
        f'{name}’s {report.get_period_type_display().lower()} progress '
        f'report for {period_label} is ready — '
        f'{totals.get("avg_best_pct", 0)}% average across '
        f'{totals.get("homework_attempted", 0)} homework.'
    )
    recipients += [(parent, parent_message) for parent in linked_parents(student)]

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

    Never raises: a bounced report email must not abort the nightly run for
    every student after this one.
    """
    from classroom.email_service import send_templated_email

    if report.period_type != TERM or report.parent_emailed_at is not None:
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
        'top_topics': report.topics[-3:][::-1],
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


def run_period(period_type, start, end, term=None, *, force=False, dry_run=False,
               notify=True):
    """Generate and deliver one window for every eligible student.

    Returns a counts dict so the management command can report what actually
    happened rather than claiming success.
    """
    school = term.school if term is not None else None
    # One cohort cache for the whole run: classmates share a class, so without
    # it a class of 25 recomputes the same figures 25 times.
    cohort_cache = {}
    counts = {
        'period': label_for(period_type, start, end, term),
        'students': 0, 'generated': 0, 'refreshed': 0,
        'notified': 0, 'emailed': 0,
    }

    for student in eligible_students(school):
        counts['students'] += 1
        if dry_run:
            continue

        report, created = generate_report(
            student, period_type, start, end, term=term, force=force,
            cohort_cache=cohort_cache,
        )
        counts['generated' if created else 'refreshed'] += 1

        if notify:
            counts['notified'] += 1 if notify_report(report) else 0
            if period_type == TERM:
                counts['emailed'] += email_parents_term_report(report)

    return counts
