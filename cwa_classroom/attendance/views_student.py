"""
attendance/views_student.py
============================
Moved from classroom/views_student.py as part of CPP-64.
Contains student-facing attendance views only.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from classroom.models import ClassStudent
from .models import ClassSession, StudentAttendance



class StudentAttendanceHistoryView(LoginRequiredMixin, View):
    """Show the student's own attendance records across all enrolled classes."""

    def get(self, request):
        # Get all classes the student belongs to
        enrolled_class_ids = ClassStudent.objects.filter(
            student=request.user
        ).values_list('classroom_id', flat=True)

        # Fetch all attendance records for this student across enrolled classes
        attendance_records = (
            StudentAttendance.objects.filter(
                student=request.user,
                session__classroom_id__in=enrolled_class_ids,
            )
            .select_related('session', 'session__classroom')
            .order_by('-session__date', '-session__start_time')
        )

        # Per-class summary statistics
        class_summaries = []
        enrolled_entries = (
            ClassStudent.objects.filter(student=request.user)
            .select_related('classroom')
            .order_by('classroom__name')
        )
        for entry in enrolled_entries:
            cls = entry.classroom
            class_attendance = attendance_records.filter(
                session__classroom=cls,
                session__status='completed',
            )
            completed_sessions = ClassSession.objects.filter(
                classroom=cls, status='completed'
            ).count()
            present = class_attendance.filter(status='present').count()
            late = class_attendance.filter(status='late').count()
            absent = class_attendance.filter(status='absent').count()
            total_marked = present + late + absent
            attendance_pct = (
                round((present + late) / completed_sessions * 100, 1)
                if completed_sessions > 0
                else None
            )
            class_summaries.append({
                'classroom': cls,
                'completed_sessions': completed_sessions,
                'present': present,
                'late': late,
                'absent': absent,
                'total_marked': total_marked,
                'attendance_pct': attendance_pct,
            })

        # Overall totals
        total_present = attendance_records.filter(
            status='present', session__status='completed'
        ).count()
        total_late = attendance_records.filter(
            status='late', session__status='completed'
        ).count()
        total_absent = attendance_records.filter(
            status='absent', session__status='completed'
        ).count()
        overall_completed = sum(s['completed_sessions'] for s in class_summaries)
        overall_pct = (
            round((total_present + total_late) / overall_completed * 100, 1)
            if overall_completed > 0
            else None
        )

        return render(request, 'student/attendance_history.html', {
            'attendance_records': attendance_records,
            'class_summaries': class_summaries,
            'total_present': total_present,
            'total_late': total_late,
            'total_absent': total_absent,
            'overall_completed': overall_completed,
            'overall_pct': overall_pct,
        })


class StudentSelfMarkAttendanceView(LoginRequiredMixin, View):
    """Allow a student to self-report attendance for a session (requires teacher approval)."""

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom'),
            id=session_id,
        )

        # Verify the student is actively enrolled in this class
        if not ClassStudent.objects.filter(
            classroom=session.classroom, student=request.user, is_active=True,
        ).exists():
            messages.error(request, 'You are not enrolled in this class.')
            return redirect('student_my_classes')

        # Only allow marking for completed sessions
        if session.status != 'completed':
            messages.error(request, 'Attendance can only be marked for completed sessions.')
            return redirect('student_class_detail', class_id=session.classroom_id)

        # Check if teacher already marked attendance for this student
        existing = StudentAttendance.objects.filter(
            session=session, student=request.user
        ).first()
        if existing and not existing.self_reported:
            messages.info(request, 'Your attendance has already been marked by the teacher.')
            return redirect('student_class_detail', class_id=session.classroom_id)

        status = request.POST.get('status', '').strip()
        if status not in ('present', 'late'):
            messages.error(request, 'Please select a valid attendance status.')
            return redirect('student_class_detail', class_id=session.classroom_id)

        StudentAttendance.objects.update_or_create(
            session=session,
            student=request.user,
            defaults={
                'status': status,
                'marked_by': request.user,
                'self_reported': True,
                'approved_by': None,
                'approved_at': None,
            },
        )

        messages.success(
            request,
            'Your attendance has been submitted and is pending teacher approval.'
        )
        return redirect('student_class_detail', class_id=session.classroom_id)


# ---------------------------------------------------------------------------
# 6. EnrollGlobalClassView
# ---------------------------------------------------------------------------