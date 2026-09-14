"""Tell the families with nothing to show WHY there is nothing (CPP-422).

Report automation used to reach a narrow slice of a school: a student had to be
in a class with that period switched on, could be narrowed further by the
"subscribed students only" filter, and a report with no activity was generated
but never notified or emailed. The families a school most wants to hear from —
the ones who never subscribed, and the ones who subscribed and then did nothing
— were exactly the ones who received silence, which a parent cannot tell apart
from the school not bothering.

With ``whole_school`` switched on (``progress.report_settings.outreach``) the
run covers **every active student in the school** and nobody is silently
skipped. A student with nothing to show produces a short note to their parents
that says so and says why:

* **no subscription** — their own ``billing.Subscription`` is not active or
  trialing, so they could not have done the work. The note carries the sign-in
  link and the school's discount code, when the school has a valid one.
* **no activity** — subscribed, but nothing was done in the window.

No-subscription wins when both are true: telling a family who never got through
the paywall that their child was idle is the wrong sentence.

Delivery is stamped in :class:`progress.models.PeriodReportNotice`, keyed on
``(student, period_type, period_start)`` and deliberately not on subject, so a
child taking maths and coding produces one note rather than two and a re-run of
the daily cron re-mails nobody.
"""

import logging

from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from progress.models import PeriodReportNotice

logger = logging.getLogger(__name__)

NO_DATA_TEMPLATE = 'email/transactional/progress_report_no_data.html'
EMAIL_NOTIFICATION_TYPE = 'progress_report_no_data'

REASON_NO_SUBSCRIPTION = PeriodReportNotice.REASON_NO_SUBSCRIPTION
REASON_NO_ACTIVITY = PeriodReportNotice.REASON_NO_ACTIVITY

#: What each reason says on the preview table. The parent-facing wording lives
#: in the email template; this is the staff-facing half of the same fact, and
#: both are driven by the one ``reason`` value so they cannot disagree.
REASON_LABELS = {
    REASON_NO_SUBSCRIPTION: 'No active subscription',
    REASON_NO_ACTIVITY: 'Nothing done this period',
}


def active_students(school):
    """Every active student of *school*, as a list of users.

    Active on both sides: the enrolment row and the account. A school that has
    deactivated a leaver has said they are gone, and a whole-school send is
    still not a reason to write to them.
    """
    from classroom.models import SchoolStudent

    return [
        row.student for row in
        SchoolStudent.objects
        .filter(school=school, is_active=True, student__is_active=True)
        .select_related('student', 'student__subscription')
        .order_by('student__first_name', 'student__last_name', 'student__username')
    ]


def reason_for(student):
    """Why this student has nothing to show — the two-valued parent-facing answer.

    Deliberately not three-valued: "in no class with reports switched on" is a
    true fact and an internal one, and a parent reading it learns about the
    school's configuration rather than about their child. Either the
    subscription is not live, or it is and nothing was done.
    """
    from billing.selectors import is_subscribed

    if not is_subscribed(student):
        return REASON_NO_SUBSCRIPTION
    return REASON_NO_ACTIVITY


def no_data_cohort(school, students_with_activity=()):
    """``[(student, reason)]`` for everyone in *school* with nothing to show.

    *students_with_activity* is the set of students this run already has a
    report **with activity** for. Everybody else in the school is in the
    cohort, whether they were in the run's classes and did nothing, are in a
    class that reports nothing, or are in no class at all — from a parent's
    side those are the same evening's silence.
    """
    done = {getattr(s, 'id', s) for s in students_with_activity}
    return [
        (student, reason_for(student))
        for student in active_students(school)
        if student.id not in done
    ]


def _site_url():
    from django.conf import settings

    return getattr(settings, 'SITE_URL', '') or ''


def notice_context(student, school, period_label, reason):
    """The email context for one note. Pure — no queries beyond the discount."""
    from billing.selectors import school_discount_offer

    site_url = _site_url()
    name = student.get_full_name() or student.username

    code, percent = (None, None)
    if reason == REASON_NO_SUBSCRIPTION and school is not None:
        # Only for the families who can act on it. A code in a "nothing done
        # this period" email reads as a sales pitch attached to bad news.
        code, percent = school_discount_offer(school)

    return {
        'student_name': name,
        'school_name': school.name if school is not None else '',
        'period_label': period_label,
        'reason': reason,
        'no_subscription': reason == REASON_NO_SUBSCRIPTION,
        'discount_code': code or '',
        'discount_percent': percent or 0,
        'login_url': f'{site_url}{reverse("login")}',
        'site_url': site_url,
    }


def send_notice(student, school, period_type, start, end, reason,
                period_label='', email=True):
    """Record and (optionally) email one "nothing to show" note. Idempotent.

    Returns ``(notice, sent, created)``: *sent* is the number of parent
    addresses reached, and *created* is False when a notice for this window
    already existed, in which case nothing is sent. That row IS the idempotency
    key, which is what lets the daily cron be re-run after a failure without a
    family hearing the same thing twice.

    *email* off records the cohort without writing to anyone: the school can
    see who the run covered, in the preview and in the command's counts,
    before letting a single note out.

    Never raises on a delivery failure. One bounced address must not abort the
    run for every family after it.
    """
    from classroom.email_service import send_templated_email
    from progress.services import linked_parents

    notice = PeriodReportNotice.objects.filter(
        student=student, period_type=period_type, period_start=start,
    ).first()
    if notice is not None:
        return notice, 0, False

    try:
        notice = PeriodReportNotice.objects.create(
            student=student, school=school, period_type=period_type,
            period_start=start, period_end=end, reason=reason,
        )
    except IntegrityError:
        # Two runs raced for the same window. The unique key held, which is the
        # point; the other run owns the send.
        notice = PeriodReportNotice.objects.filter(
            student=student, period_type=period_type, period_start=start,
        ).first()
        return notice, 0, False

    if not email:
        return notice, 0, True

    parents = [parent for parent in linked_parents(student) if parent.email]
    if not parents:
        # A real and reportable outcome, not an error: the family has no
        # address on file. Recorded with zero recipients so the run does not
        # try the same nobody again tomorrow, and so the counts say it happened.
        return notice, 0, True

    name = student.get_full_name() or student.username
    context = notice_context(student, school, period_label or str(start), reason)
    subject = (
        f'[Wizards Learning Hub] {name} — {period_label or start}: '
        f'nothing to report yet'
    )

    sent = 0
    for parent in parents:
        try:
            ok = send_templated_email(
                recipient_email=parent.email,
                subject=subject,
                template_name=NO_DATA_TEMPLATE,
                context=context,
                recipient_user=parent,
                notification_type=EMAIL_NOTIFICATION_TYPE,
                school=school,
            )
        except Exception:
            logger.exception(
                'No-data progress notice failed for student %s → %s',
                student.id, parent.email,
            )
            ok = False
        sent += 1 if ok else 0

    # Stamped whether or not every address succeeded, matching
    # PeriodReport.parent_emailed_at: the failures are in EmailLog and the
    # logger, and retrying the batch would re-mail the parents who did get it.
    notice.recipients = sent
    notice.emailed_at = timezone.now()
    notice.save(update_fields=['recipients', 'emailed_at'])
    return notice, sent, True


def run_notices(school, period_type, start, end, students_with_activity=(),
                period_label='', email=True, dry_run=False):
    """Cover the whole school for one window. Returns a counts dict.

    Counts are broken down by reason as well as totalled, because "forty
    families have no subscription" and "forty families did nothing this week"
    call for opposite conversations, and one number hides which happened.

    ``undelivered`` is the honest name for a note that was recorded but reached
    nobody — no parent address on file, or every send failed. It is counted and
    reported rather than folded into ``emailed``, because a run that quietly
    writes rows and mails no one looks identical to a successful one.
    """
    counts = {
        'cohort': 0, 'emailed': 0, 'recipients': 0,
        'already': 0, 'undelivered': 0, 'suppressed': 0,
        'by_reason': {REASON_NO_SUBSCRIPTION: 0, REASON_NO_ACTIVITY: 0},
    }

    for student, reason in no_data_cohort(school, students_with_activity):
        counts['cohort'] += 1
        counts['by_reason'][reason] += 1
        if dry_run:
            continue

        _notice, sent, created = send_notice(
            student, school, period_type, start, end, reason,
            period_label=period_label, email=email,
        )
        if not created:
            counts['already'] += 1
        elif not email:
            counts['suppressed'] += 1
        elif sent:
            counts['emailed'] += 1
            counts['recipients'] += sent
        else:
            counts['undelivered'] += 1

    return counts
