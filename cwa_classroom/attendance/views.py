"""
attendance/views.py
====================
Contains ClassAttendanceView moved from classroom/views.py (CPP-64).
"""

from django.shortcuts import get_object_or_404, render
from django.db.models import Count
from django.views import View

from accounts.models import Role
from classroom.models import ClassRoom, ClassStudent, ClassTeacher
from classroom.views import RoleRequiredMixin

from .models import ClassSession, StudentAttendance


class ClassAttendanceView(RoleRequiredMixin, View):
    required_roles = [
        Role.TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            classroom = get_object_or_404(ClassRoom, id=class_id, school__admin=user)
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            classroom = get_object_or_404(ClassRoom, id=class_id, department__head=user)
        else:
            classroom = get_object_or_404(ClassRoom, id=class_id, teachers=user)
        sessions = list(ClassSession.objects.filter(classroom=classroom, status__in=['scheduled', 'completed']).order_by('-date', '-start_time')[:20])
        enrolled_students = list(ClassStudent.objects.filter(classroom=classroom, is_active=True).select_related('student').order_by('student__last_name', 'student__first_name'))
        students = [cs.student for cs in enrolled_students]
        session_ids = [s.pk for s in sessions]
        att_qs = StudentAttendance.objects.filter(session_id__in=session_ids).values('session_id', 'student_id', 'status')
        att_map = {($a['session_id'], a['student_id']): a['status'] for a in att_qs}
        grid = []
        for student in students:
            row = {'student': student, 'cells': []}
            for session in sessions:
                row['cells'].append(att_map.get((session.pk, student.pk), ''))
            grid.append(row)
        return render(request, 'teacher/class_attendance.html', {'classroom': classroom, 'sessions': sessions, 'grid': grid})
