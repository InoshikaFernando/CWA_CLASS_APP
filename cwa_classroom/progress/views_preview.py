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
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from accounts.models import Role
from audit.services import log_event
from classroom.models import ClassRoom, Department
from classroom.views import RoleRequiredMixin
from progress import periods, report_settings
from progress.models import PeriodReport
from progress.reports import build_report_data
from progress.services import run_period, students_for_period
from progress.views_settings import _schools_for

PREVIEW_ROLES = [
    Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER, Role.ADMIN,
    Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
]


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


def _window(period_type, reference, term):
    if period_type == periods.TERM:
        if term is None:
            return None, None
        return term.start_date, term.end_date
    return periods.window_for(period_type, reference)


class ReportPreviewView(RoleRequiredMixin, View):
    """What would be sent, for every student in scope, before it is sent."""

    required_roles = PREVIEW_ROLES

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
        term = None
        if period_type == periods.TERM:
            candidates = [
                t for t in periods.most_recent_ended_terms(reference)
                if t.school_id == school.id
            ]
            term = candidates[0] if candidates else None

        start, end = _window(period_type, reference, term)

        classroom = None
        if request.GET.get('classroom'):
            classroom = ClassRoom.objects.filter(
                id=request.GET['classroom'], school=school,
            ).first()

        rows = []
        plan = {}
        if start is not None:
            plan = students_for_period(
                period_type, school=school, classroom=classroom,
            )
            for student, entry in sorted(
                plan.items(), key=lambda kv: (
                    kv[0].first_name or '', kv[0].last_name or '',
                    kv[0].username,
                ),
            ):
                # Computed, never stored. A preview that wrote rows would stamp
                # delivery state and leave the real send with nothing to do.
                data = build_report_data(
                    student, period_type, start, end, term=term,
                    classroom_ids=entry['classroom_ids'],
                )
                totals = data['totals']
                rows.append({
                    'student': student,
                    'totals': totals,
                    'awards': data['awards'],
                    'classes': data['scope']['classrooms'],
                    'has_activity': bool(totals['submissions']),
                    'delivery': entry['delivery'],
                    # Built here rather than in the template: composing it from
                    # three {% if %} blocks rendered the newlines between them
                    # as "Student , Parents".
                    'audience': _audience(entry['delivery'], bool(totals['submissions'])),
                    'already_sent': PeriodReport.objects.filter(
                        student=student, period_type=period_type,
                        period_start=start,
                    ).exclude(notified_at=None).exists(),
                })

        with_activity = [row for row in rows if row['has_activity']]
        return render(request, 'progress/report_preview.html', {
            'school': school,
            'schools': schools,
            'period_type': period_type,
            'period_choices': PeriodReport.PERIOD_CHOICES,
            'period_label': (
                periods.label_for(period_type, start, end, term)
                if start else None
            ),
            'start': start,
            'end': end,
            'term': term,
            'classroom': classroom,
            'classrooms': ClassRoom.objects.filter(
                school=school, is_active=True,
            ).order_by('name'),
            'rows': rows,
            'with_activity_count': len(with_activity),
            'average': (
                round(sum(r['totals']['avg_best_pct'] for r in with_activity)
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
        term = None
        if period_type == periods.TERM:
            candidates = [
                t for t in periods.most_recent_ended_terms(reference)
                if t.school_id == school.id
            ]
            term = candidates[0] if candidates else None
            if term is None:
                messages.error(
                    request, 'No term has ended yet, so there is nothing to send.',
                )
                return redirect('progress:report_preview')

        classroom = None
        if request.POST.get('classroom_id'):
            classroom = get_object_or_404(
                ClassRoom, id=request.POST['classroom_id'], school=school,
            )

        start, end = _window(period_type, reference, term)
        counts = run_period(
            period_type, start, end, term=term,
            school=school, classroom=classroom,
        )

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_reports_sent_manually',
            detail={
                'period_type': period_type,
                'period': counts['period'],
                'classroom_id': classroom.id if classroom else None,
                'generated': counts['generated'],
                'notified': counts['notified'],
                'emailed': counts['emailed'],
            },
            request=request,
        )

        if not counts['classes']:
            messages.warning(
                request,
                'No class in this scope has that report switched on, so '
                'nothing was sent. Switch it on under Report Automation first.',
            )
        else:
            messages.success(
                request,
                f'{counts["period"]}: generated {counts["generated"]} report(s) '
                f'for {counts["students"]} student(s); '
                f'{counts["notified"]} notified, '
                f'{counts["emailed"]} parent email(s).',
            )

        target = f'?school={school.id}&period={period_type}'
        if classroom:
            target += f'&classroom={classroom.id}'
        return redirect(f'{request.path}{target}')
