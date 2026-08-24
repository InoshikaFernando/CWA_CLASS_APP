"""Configure which classes send period reports (CPP-388 follow-up).

Reports are opt-in. This is the page where a school switches them on, at
whichever level makes sense: the whole school, one department, or one class.
The cascade is school → department → class, most specific wins; see
``progress.report_settings``.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit.services import log_event
from classroom.models import ClassRoom, Department, School, SchoolTeacher
from classroom.views import RoleRequiredMixin
from accounts.models import Role
from progress import report_settings
from progress.models import ProgressReportSetting

# Who may switch reports on. Deliberately institute-level: turning this on
# starts notifying families, which is not a per-teacher decision.
CONFIG_ROLES = [Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER, Role.ADMIN]

ALL_FIELDS = (
    ProgressReportSetting.PERIOD_FIELDS + ProgressReportSetting.DELIVERY_FIELDS
)
SCHEDULE_FIELDS = ProgressReportSetting.SCHEDULE_FIELDS

WEEKDAYS = [
    (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'),
    (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
]

FIELD_LABELS = {
    'weekly': 'Weekly',
    'monthly': 'Monthly',
    'term': 'End of term',
    'notify_student': 'Notify student',
    'notify_parents': 'Notify parents',
    'email_parents_at_term': 'Email parents at term end',
}


def _schools_for(user):
    if user.is_superuser:
        return School.objects.filter(is_active=True)
    owned = School.objects.filter(admin=user, is_active=True)
    staffed = School.objects.filter(
        is_active=True,
        id__in=SchoolTeacher.objects.filter(
            teacher=user, is_active=True,
            role__in=['head_of_institute', 'head_of_department'],
        ).values_list('school_id', flat=True),
    )
    return (owned | staffed).distinct()


def _mode(request):
    """Read the manual / automatic / inherit choice."""
    raw = request.POST.get('mode', 'inherit')
    if raw in (ProgressReportSetting.MODE_MANUAL, ProgressReportSetting.MODE_AUTO):
        return raw
    return None


def _number(request, field, low, high):
    """Read one schedule number, or None for inherit.

    Out-of-range input inherits rather than clamping: silently rewriting a
    typo into a real send day is worse than falling back to the default.
    """
    raw = (request.POST.get(field) or '').strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if low <= value <= high else None


def _tristate(request, prefix, field):
    """Read one on / off / inherit radio out of the POST body.

    Anything unrecognised is treated as "inherit" rather than as off: a form
    that half-posts should leave the cascade alone, not silently disable a
    school's reports.
    """
    raw = request.POST.get(f'{prefix}{field}', 'inherit')
    if raw == 'on':
        return True
    if raw == 'off':
        return False
    return None


class ReportSettingsView(RoleRequiredMixin, View):
    """School / department / class report configuration."""

    required_roles = CONFIG_ROLES

    def get(self, request):
        schools = _schools_for(request.user)
        school_id = request.GET.get('school')
        school = (
            schools.filter(id=school_id).first() if school_id
            else schools.first()
        )
        if school is None:
            messages.error(request, 'No school found for your account.')
            return redirect('home')

        school_row = ProgressReportSetting.objects.filter(
            school=school, department__isnull=True, classroom__isnull=True,
        ).first()

        departments = list(
            Department.objects.filter(school=school, is_active=True).order_by('name')
        )
        dept_rows = {
            row.department_id: row for row in
            ProgressReportSetting.objects.filter(
                school=school, department__isnull=False, classroom__isnull=True,
            )
        }
        for department in departments:
            department.setting = dept_rows.get(department.id)

        classrooms = list(
            ClassRoom.objects.filter(school=school, is_active=True)
            .select_related('department')
            .order_by('department__name', 'name')
        )
        class_rows = {
            row.classroom_id: row for row in
            ProgressReportSetting.objects.filter(classroom__in=classrooms)
        }
        for classroom in classrooms:
            classroom.setting = class_rows.get(classroom.id)
            resolved = report_settings.resolve(classroom)
            # The effective row is what actually happens tonight; the source
            # tells the reader which level decided it, so nobody switches off
            # a class thinking they are switching off a department.
            classroom.resolved = [
                {
                    'field': field,
                    'label': FIELD_LABELS[field],
                    'value': resolved[field][0],
                    'source': resolved[field][1],
                }
                for field in ALL_FIELDS
            ]
            classroom.sends_anything = any(
                resolved[f][0] for f in ProgressReportSetting.PERIOD_FIELDS
            )
            classroom.mode = resolved['mode'][0]
            classroom.mode_source = resolved['mode'][1]

        return render(request, 'progress/report_settings.html', {
            'school': school,
            'schools': schools,
            'school_row': school_row,
            'departments': departments,
            'classrooms': classrooms,
            'switches': [
                {'field': field, 'label': FIELD_LABELS[field]}
                for field in ALL_FIELDS
            ],
            'enabled_count': sum(1 for c in classrooms if c.sends_anything),
            'auto_count': sum(
                1 for c in classrooms
                if c.sends_anything and c.mode == ProgressReportSetting.MODE_AUTO
            ),
            'weekdays': WEEKDAYS,
            'mode_manual': ProgressReportSetting.MODE_MANUAL,
            'mode_auto': ProgressReportSetting.MODE_AUTO,
        })

    def post(self, request):
        schools = _schools_for(request.user)
        scope = request.POST.get('scope')
        school = get_object_or_404(schools, id=request.POST.get('school_id'))

        if scope == 'school':
            target, kind = school, 'school'
        elif scope == 'department':
            target = get_object_or_404(
                Department, id=request.POST.get('department_id'), school=school,
            )
            kind = 'department'
        elif scope == 'class':
            target = get_object_or_404(
                ClassRoom, id=request.POST.get('classroom_id'), school=school,
            )
            kind = 'class'
        else:
            messages.error(request, 'Unknown settings scope.')
            return redirect(f'{request.path}?school={school.id}')

        values = {field: _tristate(request, '', field) for field in ALL_FIELDS}
        values['mode'] = _mode(request)
        values['send_weekly_on'] = _number(request, 'send_weekly_on', 0, 6)
        values['send_monthly_on'] = _number(request, 'send_monthly_on', 1, 28)
        values['send_term_after_days'] = _number(request, 'send_term_after_days', 0, 60)
        report_settings.set_for(target, kind, school, values, user=request.user)

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_report_settings_changed',
            detail={
                'scope': kind,
                'target_id': getattr(target, 'id', None),
                'target': str(target),
                'values': values,
            },
            request=request,
        )
        messages.success(
            request, f'Report settings saved for {target}.',
        )
        return redirect(f'{request.path}?school={school.id}')
