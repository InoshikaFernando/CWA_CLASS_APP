"""Period progress report pages: list, detail and PDF download (CPP-388)."""

import json

from django.contrib.auth.mixins import LoginRequiredMixin
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
    attempts = report.attempts
    trend = report.trend

    # One JSON blob per chart, rendered into the page rather than fetched:
    # the snapshot is already frozen, so an extra API round-trip would only
    # add a way for the page to disagree with the PDF.
    charts = {
        'topics': {
            'labels': [row['topic'] for row in topics],
            'values': [row['accuracy_pct'] for row in topics],
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

    return {
        'report': report,
        'student': report.student,
        'is_self': report.student_id == viewer.id,
        'preview': preview,
        'pdf_url': pdf_url,
        'back_url': back_url,
        'back_label': back_label,
        'totals': report.totals,
        'topics': topics,
        'attempts': attempts,
        'awards': report.awards,
        'worksheets': report.worksheets,
        'quizzes': report.quizzes,
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
