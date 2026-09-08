"""Period progress report pages: list, detail and PDF download (CPP-388)."""

import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from progress.access import can_view_report, can_view_student
from progress.models import PeriodReport
from progress.pdf import render_report_pdf

DETAIL_TEMPLATE = 'progress/period_report_detail.html'


def _resolve_subject(request):
    """Whose reports this request is about, and whether the viewer may see them.

    Students read their own; a parent defaults to the child they have selected
    in the switcher; staff pass ``?student=<id>``. Returns
    ``(student, is_self)`` or raises 404 — never 403, which would confirm that
    another family's student exists.
    """
    from accounts.models import CustomUser

    user = request.user
    requested_id = request.GET.get('student')

    if requested_id:
        # ``?student=abc`` would otherwise reach the ORM as a ValueError and 500
        # rather than 404 — a hand-edited query string is a wrong URL, not a
        # server fault.
        if not requested_id.isdigit():
            raise Http404
        student = get_object_or_404(CustomUser, id=int(requested_id))
        if not can_view_student(user, student):
            raise Http404
        return student, student.id == user.id

    if user.is_parent:
        from classroom.views_parent import _get_active_child

        child, _school, _link = _get_active_child(request)
        if child is None:
            return None, False
        return child, False

    return user, True


def letterhead_for(report):
    """The school's letterhead for this report, or None.

    Reuses School.get_effective_settings — the same resolver invoices render
    from — rather than a second notion of "the school's letterhead". So a
    school that has set one for its invoices already has one here, and a
    department with its own logo and address gets its own, because that
    cascade is already in the settings.

    The department is taken from the classes the report covers, and only when
    they agree: a report spanning two departments has no single letterhead to
    print, and the school's is the honest fallback rather than picking one.

    Every school gets a letterhead: the logo it has set and its name, with the
    department and address added when they exist. The report is a document a
    family keeps and forwards, so whose it is has to be on it — the plain
    "Weekly Progress Report" heading never says. Only an individual learner
    with no school at all returns None.
    """
    if not report.school_id:
        return None

    department = _sole_department(report)
    settings = report.school.get_effective_settings(department)

    logo = settings.get('logo')
    address = ', '.join(
        part for part in (
            settings.get('street_address'), settings.get('city'),
            settings.get('state_region'), settings.get('postal_code'),
            settings.get('country'),
        ) if part
    )
    return {
        'logo': logo or None,
        'name': report.school.name,
        'address': address,
        'department': department.name if department else '',
    }


def _sole_department(report):
    """The one department this report's classes belong to, or None."""
    from classroom.models import ClassRoom

    ids = (report.data.get('scope') or {}).get('classroom_ids') or []
    if not ids:
        return None
    departments = {
        c.department for c in
        ClassRoom.objects.filter(id__in=ids).select_related('department')
        if c.department_id
    }
    return departments.pop() if len(departments) == 1 else None


def _manual_sections(report):
    """The teacher-authored halves: rubric assessment and narrative comment.

    Both are read live rather than frozen into ``data``. They are the one part
    of the page a teacher can still improve after a report has gone out, and
    freezing them would mean a corrected comment never reaching the family who
    already has the link.

    Either may be ``None``. Nothing here can fail a report: a section with no
    content is simply absent (CPP-395 §6).
    """
    from classroom.models import ProgressReportComment

    included = report.sections_included
    rubric = comment = None

    if included.get('include_rubric') and report.school_id:
        from classroom.views_progress import (
            _ALL_CLASSES, _build_student_progress,
        )

        # School-scoped, as everywhere else since 1.18.2 — a rubric must not
        # show another institute's assessment.
        _, overall = _build_student_progress(
            report.student, _ALL_CLASSES, report.school,
        )
        # An unassessed rubric counts nothing, and that is an absent section
        # rather than a section reading zero.
        rubric = overall if overall and overall.get('total') else None

    if included.get('include_teacher_comment') and report.school_id:
        qs = ProgressReportComment.objects.filter(
            student=report.student, school=report.school,
        ).select_related('subject', 'term', 'created_by')
        if report.subject_id:
            qs = qs.filter(
                Q(subject_id=report.subject_id) | Q(subject__isnull=True),
            )
        if report.term_id:
            qs = qs.filter(Q(term_id=report.term_id) | Q(term__isnull=True))
        comment = qs.order_by('-updated_at').first()

    return rubric, comment


def report_detail_context(report, viewer, *, preview=False,
                          pdf_url=None, back_url=None, back_label='All reports'):
    """Everything the report page renders, for a saved report or a live preview.

    Shared rather than duplicated because the preview only means something if
    it is the same page: a second copy of this assembly would drift, and a
    preview that quietly disagrees with what gets sent is worse than no
    preview at all. *report* may be an unsaved ``PeriodReport`` — nothing here
    touches the database — which is why the two URLs arrive as arguments
    instead of being reversed from ``report.id``.
    """
    topics = report.topics
    # The chart plots strands, the table below plots sub-topics. Around thirty
    # bars answered no question a parent has; "behind in Number" does, and the
    # table still carries every sub-topic.
    topic_groups = report.topic_groups
    attempts = report.attempts
    trend = report.trend

    # One JSON blob per chart, rendered into the page rather than fetched:
    # the snapshot is already frozen, so an extra API round-trip would only
    # add a way for the page to disagree with the PDF.
    charts = {
        'topics': {
            'labels': [row['topic'] for row in topic_groups],
            'values': [row['accuracy_pct'] for row in topic_groups],
        },
        'attempts': {
            'labels': [
                f"{entry['label']} attempt" + ('' if entry['label'] == '1' else 's')
                for entry in attempts.get('distribution') or []
            ],
            'values': [entry['count'] for entry in attempts.get('distribution') or []],
        },
        'trend': {
            'labels': [point['label'] for point in trend],
            'values': [point['avg_pct'] for point in trend],
        },
        'firstVsBest': {
            'labels': [row['title'] for row in attempts.get('items') or []],
            'first': [row['first_pct'] for row in attempts.get('items') or []],
            'best': [row['best_pct'] for row in attempts.get('items') or []],
        },
    }

    rubric, comment = _manual_sections(report)
    letterhead = letterhead_for(report)

    return {
        'report': report,
        'student': report.student,
        'subject': report.subject,
        'letterhead': letterhead,
        # Present only when there is something to show. A section configured on
        # but empty is omitted rather than rendered blank: a "Teacher comment"
        # heading over blank space reads as a teacher who had nothing to say,
        # and neither absence ever blocked this report being generated or sent.
        'rubric': rubric,
        'teacher_comment': comment,
        'is_self': report.student_id == viewer.id,
        'preview': preview,
        'pdf_url': pdf_url,
        'back_url': back_url,
        'back_label': back_label,
        'totals': report.totals,
        'topics': topics,
        'topic_groups': topic_groups,
        'attempts': attempts,
        'awards': report.awards,
        'worksheets': report.worksheets,
        'quizzes': report.quizzes,
        'next_steps': report.data.get('next_steps') or {},
        'subject_practice': report.subject_practice,
        'times_tables': report.times_tables,
        'basic_facts': report.basic_facts,
        'charts_json': json.dumps(charts),
    }


class PeriodReportListView(LoginRequiredMixin, View):
    """Every report generated for one student, newest first."""

    def get(self, request):
        student, is_self = _resolve_subject(request)
        if student is None:
            return render(request, 'progress/period_report_list.html', {
                'student': None, 'reports': [], 'is_self': False,
            })

        reports = list(
            PeriodReport.objects.filter(student=student)
            .select_related('term')[:60]
        )
        return render(request, 'progress/period_report_list.html', {
            'student': student,
            'is_self': is_self,
            'reports': reports,
            'latest': reports[0] if reports else None,
        })


class PeriodReportDetailView(LoginRequiredMixin, View):
    """The graphical report — Chart.js fed straight from the frozen snapshot."""

    def get(self, request, report_id):
        report = get_object_or_404(
            PeriodReport.objects.select_related('student', 'school', 'term'),
            id=report_id,
        )
        if not can_view_report(request.user, report):
            raise Http404

        back = reverse('progress:period_report_list')
        if report.student_id != request.user.id:
            back = f'{back}?student={report.student_id}'

        return render(request, DETAIL_TEMPLATE, report_detail_context(
            report, request.user,
            pdf_url=reverse('progress:period_report_pdf',
                            kwargs={'report_id': report.id}),
            back_url=back,
        ))


class PeriodReportPdfView(LoginRequiredMixin, View):
    """The same report as a download."""

    def get(self, request, report_id):
        report = get_object_or_404(
            PeriodReport.objects.select_related('student', 'school', 'term'),
            id=report_id,
        )
        if not can_view_report(request.user, report):
            raise Http404

        pdf = render_report_pdf(report)
        filename = (
            f'{report.student.username}-{report.period_type}-'
            f'{report.period_start:%Y-%m-%d}.pdf'
        )
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
