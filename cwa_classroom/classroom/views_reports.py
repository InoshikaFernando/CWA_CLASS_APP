import logging
from django import forms
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render

from accounts.models import Role
from classroom.models import ClassRoom, ClassStudent, Department, School, SchoolStudent, SchoolTeacher
from classroom.views import RoleRequiredMixin, _get_user_school_ids

from django.views import View

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


class ReportFilterForm(forms.Form):
    class_id = forms.IntegerField(required=False)
    status = forms.ChoiceField(
        choices=[('all', 'All'), ('active', 'Active'), ('inactive', 'Inactive')],
        required=False,
        initial='all',
    )
    payment = forms.ChoiceField(
        choices=[('all', 'All'), ('blocked', 'Payment blocked'), ('ok', 'OK')],
        required=False,
        initial='all',
    )
    no_class = forms.BooleanField(required=False)


def _get_all_school_ids(user):
    """School IDs accessible to any admin role — HoI, Owner, HoD, or school admin."""
    if user.is_superuser:
        return list(School.objects.filter(is_active=True).values_list('id', flat=True))
    via_school_teacher = set(
        SchoolTeacher.objects.filter(teacher=user, is_active=True).values_list('school_id', flat=True)
    )
    via_admin = set(School.objects.filter(admin=user, is_active=True).values_list('id', flat=True))
    via_dept = set(Department.objects.filter(head=user, is_active=True).values_list('school_id', flat=True))
    via_class = set(ClassRoom.objects.filter(teachers=user, is_active=True).values_list('school_id', flat=True))
    return list(via_school_teacher | via_admin | via_dept | via_class)


def _get_hod_dept_ids(user):
    """Return department IDs accessible to a HoD-only user."""
    headed = list(Department.objects.filter(head=user, is_active=True).values_list('id', flat=True))
    teaching = list(
        ClassRoom.objects.filter(teachers=user, is_active=True, department__isnull=False)
        .values_list('department_id', flat=True)
        .distinct()
    )
    return list(set(headed) | set(teaching))


def _is_hod_only(user):
    return (
        user.has_role(Role.HEAD_OF_DEPARTMENT)
        and not user.has_role(Role.HEAD_OF_INSTITUTE)
        and not user.has_role(Role.INSTITUTE_OWNER)
        and not user.is_superuser
    )


class StudentReportView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        school_ids = _get_all_school_ids(request.user)
        hod_only = _is_hod_only(request.user)
        dept_ids = _get_hod_dept_ids(request.user) if hod_only else []

        # Classes available for filter dropdown — scoped to accessible dept/school
        if hod_only:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids,
                department_id__in=dept_ids,
                is_active=True,
            ).order_by('name')
        else:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids,
                is_active=True,
            ).order_by('name')

        form = ReportFilterForm(request.GET or None)
        filters = {}
        if form.is_valid():
            filters = form.cleaned_data

        # Base queryset — school-scoped
        qs = SchoolStudent.objects.filter(
            school_id__in=school_ids,
        ).select_related('student').annotate(
            active_class_count=Count(
                'student__class_student_entries',
                filter=Q(
                    student__class_student_entries__is_active=True,
                    student__class_student_entries__classroom__school_id__in=school_ids,
                ),
                distinct=True,
            )
        )

        # HoD: restrict to students in their departments' classes
        if hod_only and dept_ids:
            dept_student_ids = ClassStudent.objects.filter(
                classroom__department_id__in=dept_ids,
                classroom__school_id__in=school_ids,
                is_active=True,
            ).values_list('student_id', flat=True).distinct()
            qs = qs.filter(student_id__in=dept_student_ids)
        elif hod_only and not dept_ids:
            qs = qs.none()

        # Apply filters
        class_id = filters.get('class_id')
        if class_id:
            class_student_ids = ClassStudent.objects.filter(
                classroom_id=class_id,
                classroom__school_id__in=school_ids,
                is_active=True,
            ).values_list('student_id', flat=True)
            qs = qs.filter(student_id__in=class_student_ids)

        status = filters.get('status') or 'all'
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        payment = filters.get('payment') or 'all'
        if payment == 'blocked':
            qs = qs.filter(student__is_blocked=True)
        elif payment == 'ok':
            qs = qs.filter(student__is_blocked=False)

        if filters.get('no_class'):
            qs = qs.filter(active_class_count=0)

        qs = qs.order_by('student__first_name', 'student__last_name')

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'page_obj': page_obj,
            'form': form,
            'available_classes': available_classes,
            'total_count': qs.count(),
            'filters': filters,
            'is_hod_only': hod_only,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'reports/_partials/student_report_table.html', context)

        return render(request, 'reports/students.html', context)
