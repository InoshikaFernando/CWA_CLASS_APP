"""
attendance/views.py
====================
Attendance views for class attendance grids and HoD attendance reports.
Decoupled from classroom app as part of CPP-64.
"""

from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from accounts.models import CustomUser, Role
from billing.mixins import ModuleRequiredMixin
from billing.models import ModuleSubscription
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, School,
)
from classroom.views import RoleRequiredMixin

from .models import ClassSession, StudentAttendance, TeacherAttendance


class ClassAttendanceView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            # HoD can view classes in their department OR classes they teach
            classroom = ClassRoom.objects.filter(
                Q(department__head=user) | Q(teachers=user),
                id=class_id,
            ).distinct().first()
            if not classroom:
                raise Http404
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=user)

        # Last 20 non-cancelled sessions, most recent first
        sessions = list(
            ClassSession.objects.filter(
                classroom=classroom,
                status__in=['scheduled', 'completed'],
            ).order_by('-date', '-start_time')[:20]
        )

        active_ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)
        students = CustomUser.objects.filter(id__in=active_ids).order_by('last_name', 'first_name', 'username')

        # Batch-fetch all attendance records for these sessions
        att_map = {}
        if sessions:
            for rec in StudentAttendance.objects.filter(session__in=sessions):
                att_map[(rec.session_id, rec.student_id)] = rec.status

        # Build per-student rows
        student_data = []
        for student in students:
            present = late = absent = 0
            row_sessions = []
            for session in sessions:
                status = att_map.get((session.id, student.id))
                row_sessions.append(status)
                if status == 'present':
                    present += 1
                elif status == 'late':
                    late += 1
                elif status == 'absent':
                    absent += 1
            total = present + late + absent
            rate = round((present + late) / total * 100) if total else None
            student_data.append({
                'student': student,
                'cells': row_sessions,
                'present': present,
                'late': late,
                'absent': absent,
                'total': total,
                'rate': rate,
            })

        return render(request, 'teacher/class_attendance.html', {
            'classroom': classroom,
            'sessions': sessions,
            'student_data': student_data,
        })


class HoDAttendanceReportView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if is_hod_only:
            dept_ids = list(
                Department.objects.filter(head=request.user, is_active=True).values_list('id', flat=True)
            )
            teaching_class_ids = list(
                ClassRoom.objects.filter(teachers=request.user, is_active=True).values_list('id', flat=True)
            )
            class_filter = Q(session__classroom__department_id__in=dept_ids) | Q(session__classroom_id__in=teaching_class_ids)
            teacher_att_qs = TeacherAttendance.objects.filter(class_filter)
            student_att_qs = StudentAttendance.objects.filter(class_filter)
        else:
            my_school_ids = list(School.objects.filter(admin=request.user).values_list('id', flat=True))
            teacher_att_qs = TeacherAttendance.objects.filter(
                session__classroom__school_id__in=my_school_ids,
            )
            student_att_qs = StudentAttendance.objects.filter(
                session__classroom__school_id__in=my_school_ids,
            )

        teacher_summary = (
            teacher_att_qs
            .values('teacher__id', 'teacher__username', 'teacher__first_name', 'teacher__last_name')
            .annotate(
                total_sessions=Count('id'),
                present_count=Count('id', filter=Q(status='present')),
                absent_count=Count('id', filter=Q(status='absent')),
            )
            .order_by('teacher__last_name', 'teacher__first_name')
        )

        # --- Student attendance summary ---
        student_summary = (
            student_att_qs
            .values('student__id', 'student__username', 'student__first_name', 'student__last_name')
            .annotate(
                total_sessions=Count('id'),
                present_count=Count('id', filter=Q(status='present')),
                absent_count=Count('id', filter=Q(status='absent')),
                late_count=Count('id', filter=Q(status='late')),
            )
            .order_by('student__last_name', 'student__first_name')
        )

        return render(request, 'hod/attendance_report.html', {
            'teacher_summary': teacher_summary,
            'student_summary': student_summary,
        })


class AttendanceDetailView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Return session-level attendance detail for a teacher or student (HTMX partial)."""
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        user_type = request.GET.get('type')  # 'teacher' or 'student'
        user_id = request.GET.get('user_id')
        status_filter = request.GET.get('status', 'all')

        if user_type not in ('teacher', 'student') or not user_id:
            return HttpResponse('')

        is_hod_only = (
            request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            and not request.user.has_role(Role.HEAD_OF_INSTITUTE)
            and not request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if user_type == 'teacher':
            qs = TeacherAttendance.objects.filter(teacher_id=user_id)
            if is_hod_only:
                dept_ids = list(
                    Department.objects.filter(head=request.user, is_active=True)
                    .values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__department_id__in=dept_ids)
            else:
                school_ids = list(
                    School.objects.filter(admin=request.user).values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__school_id__in=school_ids)

            if status_filter and status_filter != 'all':
                qs = qs.filter(status=status_filter)

            records = qs.select_related('session', 'session__classroom').order_by('-session__date', '-session__start_time')
        else:
            qs = StudentAttendance.objects.filter(student_id=user_id)
            if is_hod_only:
                dept_ids = list(
                    Department.objects.filter(head=request.user, is_active=True)
                    .values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__department_id__in=dept_ids)
            else:
                school_ids = list(
                    School.objects.filter(admin=request.user).values_list('id', flat=True)
                )
                qs = qs.filter(session__classroom__school_id__in=school_ids)

            if status_filter and status_filter != 'all':
                qs = qs.filter(status=status_filter)

            records = qs.select_related('session', 'session__classroom').order_by('-session__date', '-session__start_time')

        return render(request, 'hod/attendance_detail_partial.html', {
            'records': records,
            'user_type': user_type,
            'status_filter': status_filter,
        })
