"""Preview every student's report before anything is sent (CPP-388 follow-up).

Manual mode is the default, which only means something if staff can actually
see what they would be sending. This page computes the reports for a closed
window **without saving them**, shows one row per student, and offers a single
"Generate and send" action for the scope.

Nothing here writes until the POST: a preview that quietly created rows would
make "preview" a lie, and would also stamp delivery state so the real send
later found nothing to do.
"""

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from accounts.models import Role
from audit.services import log_event
from classroom.models import ClassRoom, Department
from billing import selectors as billing_selectors
from billing.mixins import ModuleRequiredMixin
from billing.models import ModuleSubscription
from classroom.views import RoleRequiredMixin
from progress import periods, report_settings, reports
from progress.models import PeriodReport
from progress.pdf import render_report_pdf
from progress.reports import build_report_data
from progress.services import (
    classrooms_for_period, run_period, students_for_period,
)
from progress import outreach
from progress.views_reports import DETAIL_TEMPLATE, report_detail_context
from progress.views_settings import _schools_for

PREVIEW_ROLES = [
    Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER, Role.ADMIN,
    Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
]


def _activity_summary(data):
    """A compact "what they actually did" phrase for the preview table.

    Built here rather than in the template so the empty strands drop out
    cleanly — a row reading "3 homework · 0 quizzes · 0 tables" buries the one
    number that matters in two that do not.
    """
    totals = data['totals']
    parts = []
    if totals['homework_attempted']:
        parts.append(f"{totals['homework_attempted']} homework")
    if data['quizzes']['attempted']:
        parts.append(f"{data['quizzes']['attempted']} quiz")
    if data['times_tables']['tables']:
        parts.append(f"{data['times_tables']['tables']} tables")
    if data['basic_facts']['subtopics']:
        parts.append(f"{data['basic_facts']['subtopics']} basic facts")
    practice = data.get('subject_practice') or {}
    if practice.get('items'):
        parts.append(f"{practice['items']} practice")
    if data['worksheets']['completed']:
        parts.append(f"{data['worksheets']['completed']} worksheets")
    return ' · '.join(parts)


def _audience(delivery, has_activity):
    """Who this report would actually reach, as a reader-facing phrase."""
    if not has_activity:
        return '—'
    who = []
    if delivery['notify_student']:
        who.append('Student')
    if delivery['notify_parents']:
        who.append('Parents')
    return ', '.join(who) if who else 'Nobody (silent)'


def _resolve_term(school, reference, requested=None):
    """Which term this page is showing, and whether it is still running.

    Returns ``(term, partial, terms)`` where *terms* is everything the school
    may choose between. ONE resolver, used by the table and by the single
    student's page behind "View report": they used to hold a copy each, and a
    copy each is how a link opens a different term from the row it came from.

    ``?term=<id>`` picks a specific term, validated against this school's own
    terms — a foreign or future id falls back to the default rather than 404ing
    a reader out of a page they may legitimately read.
    """
    terms = periods.reviewable_terms(school, reference)
    term = None
    if requested and str(requested).isdigit():
        term = next((t for t in terms if t.id == int(requested)), None)
    if term is None:
        term = periods.default_term(terms, reference)
    return term, periods.term_in_progress(term, reference), terms


def _window(period_type, reference, term, partial=False):
    """The window on screen. ``(start, end)``; ``(None, None)`` if there is none.

    A term still running stops at *reference*, not at its end date — see
    ``periods.term_window``.
    """
    if period_type == periods.TERM:
        if term is None:
            return None, None
        start, end, _partial = periods.term_window(term, reference)
        return start, end
    return periods.window_for(period_type, reference)


def _subject_order(entry, subjects):
    """This student's subjects, in the order the table shows them."""
    return sorted(
        entry['by_subject'].items(),
        key=lambda kv: (
            kv[0] is None,
            subjects[kv[0]].name if kv[0] in subjects else '',
        ),
    )


def _subjects_by_id(plan):
    from classroom.models import Subject

    ids = {
        subject_id
        for entry in plan.values()
        for subject_id in entry['by_subject']
        if subject_id is not None
    }
    return {s.id: s for s in Subject.objects.filter(id__in=ids)} if ids else {}


def _teacher_comment(student, school, term, subject):
    """The teacher's narrative for this student, subject and term, if written.

    Returned so the preview can say a comment is missing WITHOUT that stopping
    anything: staff may choose to write one before sending, but a report is
    never held up waiting for one (CPP-395 §6).
    """
    from classroom.models import ProgressReportComment

    if school is None:
        return None
    qs = ProgressReportComment.objects.filter(student=student, school=school)
    if subject is not None:
        qs = qs.filter(Q(subject=subject) | Q(subject__isnull=True))
    if term is not None:
        qs = qs.filter(Q(term=term) | Q(term__isnull=True))
    # Most recently edited wins: a teacher who updates a comment expects the
    # update to be what goes out.
    return qs.order_by('-updated_at').first()


def _requested_subject(entry, raw):
    """Resolve ``?subject=`` against the subjects this student actually has.

    Returns ``(subject, classroom_ids)``. An unknown or absent id falls back to
    every class — which is what a link written before CPP-395 means, and is
    also the honest answer for a student whose classes carry no subject.
    """
    from classroom.models import Subject

    if raw and raw.isdigit():
        subject_id = int(raw)
        if subject_id in entry['by_subject']:
            subject = Subject.objects.filter(id=subject_id).first()
            if subject is not None:
                return subject, entry['by_subject'][subject_id]
    return None, entry['classroom_ids']


def _preview_row(student, entry, subject, class_ids, period_type, start, end,
                 term, school, partial=False):
    """One student's report for one subject — computed, never stored.

    A preview that wrote rows would stamp delivery state and leave the real
    send with nothing to do.
    """
    data = build_report_data(
        student, period_type, start, end, term=term,
        classroom_ids=class_ids, subject=subject,
        content=entry['content'].get(subject.id if subject else None),
        partial=partial,
    )
    totals = data['totals']
    # The same rule the generator applies, not a stricter local one:
    # testing submissions alone hid every child whose week was practice,
    # worksheets or quizzes, and told staff nothing would be sent to them
    # when in fact it would.
    active = reports.has_activity(data)
    return {
        'student': student,
        'subject': subject,
        # Named here rather than in the template so the two empty cases read
        # differently: a class with no subject set is not a subject.
        'subject_label': subject.name if subject else 'No subject set',
        'teacher_comment': _teacher_comment(student, school, term, subject),
        'activity': _activity_summary(data),
        'quizzes': data['quizzes'],
        'times_tables': data['times_tables'],
        'basic_facts': data['basic_facts'],
        'worksheets': data['worksheets'],
        'totals': totals,
        'awards': data['awards'],
        'classes': data['scope']['classrooms'],
        'has_activity': active,
        'delivery': entry['delivery'],
        # Built here rather than in the template: composing it from three
        # {% if %} blocks rendered the newlines between them as "Student , Parents".
        'audience': _audience(entry['delivery'], active),
        'already_sent': PeriodReport.objects.filter(
            student=student, period_type=period_type,
            period_start=start, subject=subject,
        ).exclude(notified_at=None).exists(),
    }


def _no_data_rows(school, rows, period_type, start, classroom, subscribed_only):
    """The whole-school cohort, for the school that asked to cover it (CPP-422).

    Returned as its own list rather than mixed into *rows*: those are one per
    student PER SUBJECT, and this cohort has no subject — a student in no
    reporting class has nothing for a report to be about. One row per student,
    which is also exactly how many notes get sent.

    Empty in the two scopes the send itself skips (see
    ``progress.services._run_outreach``): a single-class preview and a
    subscribed-only one. Showing a cohort the button would not mail is the
    precise disagreement between page and send that this page exists to avoid.
    """
    from progress.models import PeriodReportNotice

    if classroom is not None or subscribed_only:
        return []
    if not report_settings.covers_whole_school(school):
        return []

    with_activity = {row['student'].id for row in rows if row['has_activity']}
    cohort = outreach.no_data_cohort(school, with_activity)
    if not cohort:
        return []

    already = set(
        PeriodReportNotice.objects
        .filter(
            student_id__in=[student.id for student, _reason in cohort],
            period_type=period_type, period_start=start,
        )
        .values_list('student_id', flat=True)
    )
    return [
        {
            'student': student,
            'reason': reason,
            'reason_label': outreach.REASON_LABELS[reason],
            'no_subscription': reason == outreach.REASON_NO_SUBSCRIPTION,
            'already_sent': student.id in already,
        }
        for student, reason in cohort
    ]


class ReportPreviewView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """What would be sent, for every student in scope, before it is sent."""

    required_roles = PREVIEW_ROLES
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS

    def get(self, request):
        schools = _schools_for(request.user)
        school = (
            schools.filter(id=request.GET.get('school')).first()
            if request.GET.get('school') else schools.first()
        )
        if school is None:
            messages.error(request, 'No school found for your account.')
            return redirect('home')

        period_type = request.GET.get('period', periods.WEEKLY)
        if not periods.is_valid_period(period_type):
            period_type = periods.WEEKLY

        reference = periods.today()
        term, term_partial, terms = (None, False, [])
        if period_type == periods.TERM:
            term, term_partial, terms = _resolve_term(
                school, reference, request.GET.get('term'),
            )

        start, end = _window(period_type, reference, term, term_partial)

        classroom = None
        if request.GET.get('classroom'):
            classroom = ClassRoom.objects.filter(
                id=request.GET['classroom'], school=school,
            ).first()

        # "Subscribed students only" — the same rule the Manage Students list
        # uses (billing.selectors). Applied inside the plan, not over the rows,
        # so the send below covers exactly what this page shows.
        subscribed_only = request.GET.get('subscribed') == '1'

        rows = []
        plan = {}
        empty_reason = None
        if start is None:
            # Only a term window can be missing: a term report covers a term
            # that has ended, and this school has none.
            empty_reason = 'no_period'
        else:
            plan = students_for_period(
                period_type, school=school, classroom=classroom,
                subscribed_only=subscribed_only,
            )
            subjects = _subjects_by_id(plan)
            ordered = sorted(plan.items(), key=lambda kv: (
                kv[0].first_name or '', kv[0].last_name or '', kv[0].username,
            ))
            for student, entry in ordered:
                # One row per subject, so "All classes" shows what would
                # actually be sent: a student taking maths, coding and science
                # appears three times. The repeated name is correct — the
                # subject is what makes each row a different report.
                for subject_id, class_ids in _subject_order(entry, subjects):
                    rows.append(_preview_row(
                        student, entry, subjects.get(subject_id), class_ids,
                        period_type, start, end, term, school,
                        partial=term_partial,
                    ))

            if not rows:
                # An empty plan has three causes that call for opposite
                # actions: drop the filter, switch the report on, or put
                # students in the class. Naming the wrong one sends a head of
                # institute to change a setting that is already correct.
                if subscribed_only and students_for_period(
                    period_type, school=school, classroom=classroom,
                ):
                    empty_reason = 'no_subscribed'
                else:
                    empty_reason = (
                        'no_students'
                        if classrooms_for_period(
                            period_type, school=school, classroom=classroom,
                        )
                        else 'not_enabled'
                    )

        with_activity = [row for row in rows if row['has_activity']]
        no_data_rows = (
            _no_data_rows(
                school, rows, period_type, start, classroom, subscribed_only,
            )
            if start is not None else []
        )
        outreach_flags = report_settings.outreach(school)
        return render(request, 'progress/report_preview.html', {
            'school': school,
            'schools': schools,
            'period_type': period_type,
            'period_choices': PeriodReport.PERIOD_CHOICES,
            'period_label': (
                periods.label_for(
                    period_type, start, end, term, partial=term_partial)
                if start else None
            ),
            'start': start,
            'end': end,
            'term': term,
            'terms': terms,
            # So the selector can mark which term is still running. Passed
            # rather than computed in the template: "today" is the one value
            # the whole page's partial/final split turns on.
            'today': reference,
            # A term still running is reviewable and NOT sendable; the template
            # drops the send button and says why. See services.PartialWindowError.
            'term_partial': term_partial,
            'classroom': classroom,
            'subscribed_only': subscribed_only,
            'classrooms': ClassRoom.objects.filter(
                school=school, is_active=True,
            ).order_by('name'),
            'rows': rows,
            'empty_reason': empty_reason,
            'with_activity_count': len(with_activity),
            'no_data_rows': no_data_rows,
            'whole_school': outreach_flags['whole_school'],
            'email_no_data': outreach_flags['email_parents_no_data'],
            'discount_code': (
                billing_selectors.school_discount_offer(school)[0] or ''
            ),
            'average': (
                round(sum(r['totals']['overall_avg_pct'] for r in with_activity)
                      / len(with_activity))
                if with_activity else 0
            ),
        })

    def post(self, request):
        """Generate and send for the previewed scope. Staff-triggered only."""
        schools = _schools_for(request.user)
        school = get_object_or_404(schools, id=request.POST.get('school_id'))

        period_type = request.POST.get('period', periods.WEEKLY)
        if not periods.is_valid_period(period_type):
            messages.error(request, 'Unknown report period.')
            return redirect('progress:report_preview')

        reference = periods.today()
        term, term_partial = None, False
        if period_type == periods.TERM:
            # The term the reader was looking at, resolved the same way the
            # page resolved it: sending a different term from the one on screen
            # is the exact failure this page exists to prevent.
            term, term_partial, _terms = _resolve_term(
                school, reference, request.POST.get('term_id'),
            )
            if term is None:
                messages.error(
                    request, 'No term has ended yet, so there is nothing to send.',
                )
                return redirect('progress:report_preview')
            if term_partial:
                # The template does not offer the button here, so this is a
                # hand-made POST. Refused rather than obeyed: a stored mid-term
                # report takes the place of the real end-of-term one, and the
                # family never receives that. See services.PartialWindowError.
                messages.error(
                    request,
                    f'{term.name} has not ended yet, so its report cannot be '
                    f'sent — a report stored now would take the place of the '
                    f'real end-of-term one. Review it here as often as you '
                    f'like; it sends once the term closes.',
                )
                return redirect(
                    f'{request.path}?school={school.id}'
                    f'&period={period_type}&term={term.id}'
                )

        classroom = None
        if request.POST.get('classroom_id'):
            classroom = get_object_or_404(
                ClassRoom, id=request.POST['classroom_id'], school=school,
            )

        start, end = _window(period_type, reference, term, term_partial)
        # The scope the previewed page was showing, carried through the form:
        # sending a wider set than the one on screen is the exact failure the
        # preview exists to prevent.
        subscribed_only = request.POST.get('subscribed') == '1'
        counts = run_period(
            period_type, start, end, term=term,
            school=school, classroom=classroom,
            subscribed_only=subscribed_only,
        )

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_reports_sent_manually',
            detail={
                'period_type': period_type,
                'period': counts['period'],
                'term_id': term.id if term else None,
                'classroom_id': classroom.id if classroom else None,
                'subscribed_only': subscribed_only,
                'generated': counts['generated'],
                'notified': counts['notified'],
                'emailed': counts['emailed'],
                'notices': counts['notices'],
                'notices_emailed': counts['notices_emailed'],
            },
            request=request,
        )

        # Whole-school coverage can make a run meaningful even when no class
        # produced a report, so the "nothing was sent" warnings below have to
        # consider it — otherwise a run that mailed forty families reports
        # itself as a no-op.
        if not counts['classes'] and not counts['notices']:
            # With the filter on, an empty run has a second cause — the classes
            # are switched on but hold nobody subscribed — and sending staff to
            # Report Automation for that is sending them to a correct setting.
            if subscribed_only:
                messages.warning(
                    request,
                    'Nothing was sent: no subscribed student is in a class '
                    'with that report switched on. Clear the "Subscribed '
                    'students only" filter, or switch the report on under '
                    'Report Automation first.',
                )
            else:
                messages.warning(
                    request,
                    'No class in this scope has that report switched on, so '
                    'nothing was sent. Switch it on under Report Automation '
                    'first.',
                )
        else:
            summary = (
                f'{counts["period"]}: generated {counts["generated"]} report(s) '
                f'for {counts["students"]} student(s); '
                f'{counts["notified"]} notified, '
                f'{counts["emailed"]} parent email(s).'
            )
            if counts['notices']:
                summary += (
                    f' {counts["notices"]} student(s) had nothing to show; '
                    f'{counts["notices_emailed"]} note(s) sent to '
                    f'{counts["notices_recipients"]} parent address(es).'
                )
            if counts['notices_undelivered']:
                # Said out loud rather than folded into the count above: a note
                # that reached nobody is the silence this feature exists to end.
                summary += (
                    f' {counts["notices_undelivered"]} reached nobody — '
                    f'no parent email on file, or delivery failed.'
                )
            messages.success(request, summary)

        target = f'?school={school.id}&period={period_type}'
        if classroom:
            target += f'&classroom={classroom.id}'
        if term:
            target += f'&term={term.id}'
        if subscribed_only:
            target += '&subscribed=1'
        return redirect(f'{request.path}{target}')


def _preview_query(school, period_type, classroom=None, student=None,
                   subscribed_only=False, term=None):
    """The query string that pins a preview to one scope, and optionally one student."""
    query = f'?school={school.id}&period={period_type}'
    if classroom is not None:
        query += f'&classroom={classroom.id}'
    if student is not None:
        query += f'&student={student.id}'
    # Without this, opening one student from a term the reader had *chosen*
    # dropped them back onto the default term — a different report under the
    # same link.
    if term is not None:
        query += f'&term={term.id}'
    # Carried so "Back to preview" returns to the filtered list the reader came
    # from rather than silently widening it.
    if subscribed_only:
        query += '&subscribed=1'
    return query


def _no_student_yet(request):
    """True when the URL names no student at all.

    Distinct from naming one this viewer may not see, which is a 404. Arriving
    at the bare URL — a truncated link, a bookmark, a walk of the route table —
    is not an error and must not dead-end: send them to the list that carries
    the links.
    """
    return not request.GET.get('student')


def _resolve_one(request):
    """The scope, and the single student's live report within it.

    Access is deliberately decided by *the same plan that builds the table*
    rather than by a fresh permission rule: if a row for this student is on the
    preview list this user just looked at, they may open it, and if it is not,
    they may not. A second rule here would either 404 on rows the page shows —
    a link that is a trap — or grant something the list does not.

    Returns ``(school, report, period_type, classroom)`` with *report* an
    unsaved ``PeriodReport``. Raises 404 rather than 403 throughout, matching
    ``progress.access``: confirming that another school's student exists is
    itself a leak.
    """
    schools = _schools_for(request.user)
    school = schools.filter(id=request.GET.get('school')).first()
    if school is None:
        raise Http404

    period_type = request.GET.get('period', periods.WEEKLY)
    if not periods.is_valid_period(period_type):
        raise Http404

    reference = periods.today()
    term, term_partial = None, False
    if period_type == periods.TERM:
        term, term_partial, _terms = _resolve_term(
            school, reference, request.GET.get('term'),
        )

    start, end = _window(period_type, reference, term, term_partial)
    if start is None:
        raise Http404

    classroom = None
    if request.GET.get('classroom'):
        classroom = ClassRoom.objects.filter(
            id=request.GET['classroom'], school=school,
        ).first()
        if classroom is None:
            raise Http404

    # ``?student=abc`` would otherwise reach the ORM as a ValueError and 500
    # rather than 404 — a hand-edited query string is a wrong URL, not a fault.
    requested = request.GET.get('student') or ''
    if not requested.isdigit():
        raise Http404

    plan = students_for_period(period_type, school=school, classroom=classroom)
    match = next(
        ((student, entry) for student, entry in plan.items()
         if student.id == int(requested)),
        None,
    )
    if match is None:
        raise Http404
    student, entry = match

    # The subject the preview row was for. Without it this page rebuilt the
    # student's whole timetable — the table fanned out per subject but the
    # link back into it did not, so "View report" showed a combined report
    # that no longer matches anything the send would produce.
    subject, class_ids = _requested_subject(entry, request.GET.get('subject'))

    data = build_report_data(
        student, period_type, start, end, term=term,
        classroom_ids=class_ids, subject=subject,
        content=entry['content'].get(subject.id if subject else None),
        partial=term_partial,
    )
    # Unsaved on purpose: this is the object the real send would create, built
    # the same way, and never written. Constructing it means the preview page
    # and the PDF read the snapshot through exactly the model properties the
    # sent report uses, instead of a parallel path that could disagree.
    report = PeriodReport(
        student=student, school=school, term=term, subject=subject,
        period_type=period_type, period_start=start, period_end=end,
        data=data,
    )
    return school, report, period_type, classroom, term


class ReportPreviewDetailView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """One student's report as the family would see it, computed and discarded."""

    required_roles = PREVIEW_ROLES
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS

    def get(self, request):
        if _no_student_yet(request):
            return redirect('progress:report_preview')

        school, report, period_type, classroom, term = _resolve_one(request)
        subscribed_only = request.GET.get('subscribed') == '1'
        scope = _preview_query(
            school, period_type, classroom, subscribed_only=subscribed_only,
            term=term,
        )
        student_scope = _preview_query(
            school, period_type, classroom, student=report.student,
            subscribed_only=subscribed_only, term=term,
        )
        return render(request, DETAIL_TEMPLATE, report_detail_context(
            report, request.user, preview=True,
            pdf_url=f"{reverse('progress:report_preview_pdf')}{student_scope}",
            back_url=f"{reverse('progress:report_preview')}{scope}",
            back_label='Back to preview',
        ))


class ReportPreviewPdfView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """The preview as the PDF a parent would be sent. Also saves nothing."""

    required_roles = PREVIEW_ROLES
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS

    def get(self, request):
        if _no_student_yet(request):
            return redirect('progress:report_preview')

        _school, report, _period_type, _classroom, _term = _resolve_one(request)
        pdf = render_report_pdf(report)
        filename = (
            f'preview-{report.student.username}-{report.period_type}-'
            f'{report.period_start:%Y-%m-%d}.pdf'
        )
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
