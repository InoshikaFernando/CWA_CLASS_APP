from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone

from accounts.models import Role
from .views import RoleRequiredMixin
from .models import (
    ClassRoom, ClassStudent, Enrollment, ClassSession,
    StudentAttendance, Notification, Department,
)


class JoinClassByCodeView(RoleRequiredMixin, View):
    """Allow a student to request enrollment in a class by entering its code."""
    required_roles = [Role.STUDENT, Role.INDIVIDUAL_STUDENT]

    def get(self, request):
        return render(request, 'student/join_class.html')

    def post(self, request):
        code = request.POST.get('code', '').strip().upper()

        if not code:
            messages.error(request, 'Please enter a class code.')
            return render(request, 'student/join_class.html')

        # Look up the classroom by its unique code
        try:
            classroom = ClassRoom.objects.get(code=code, is_active=True)
        except ClassRoom.DoesNotExist:
            messages.error(request, 'No active class found with that code.')
            return render(request, 'student/join_class.html', {'code': code})

        # Check if student is already a member of this class
        if ClassStudent.objects.filter(
            classroom=classroom, student=request.user
        ).exists():
            messages.info(
                request,
                f'You are already enrolled in "{classroom.name}".',
            )
            return render(request, 'student/join_class.html', {'code': code})

        # Check if an enrollment request already exists (any status)
        existing_enrollment = Enrollment.objects.filter(
            classroom=classroom, student=request.user
        ).first()

        if existing_enrollment:
            if existing_enrollment.status == 'pending':
                messages.info(
                    request,
                    f'You already have a pending request for "{classroom.name}". '
                    'Please wait for teacher approval.',
                )
            elif existing_enrollment.status == 'approved':
                messages.info(
                    request,
                    f'Your enrollment in "{classroom.name}" has already been approved.',
                )
            elif existing_enrollment.status == 'rejected':
                # Allow re-requesting after rejection: reset to pending
                existing_enrollment.status = 'pending'
                existing_enrollment.requested_at = timezone.now()
                existing_enrollment.rejection_reason = ''
                existing_enrollment.save(
                    update_fields=['status', 'requested_at', 'rejection_reason']
                )
                # Notify teachers about the re-request
                _notify_class_teachers(classroom, request.user, is_re_request=True)
                messages.success(
                    request,
                    f'Your enrollment request for "{classroom.name}" has been '
                    're-submitted. Please wait for teacher approval.',
                )
            return render(request, 'student/join_class.html', {'code': code})

        # Create a new pending enrollment request
        Enrollment.objects.create(
            classroom=classroom,
            student=request.user,
            status='pending',
        )

        # Notify the class teacher(s) about the new enrollment request
        _notify_class_teachers(classroom, request.user)

        messages.success(
            request,
            f'Your enrollment request for "{classroom.name}" has been submitted. '
            'Please wait for teacher approval.',
        )
        return redirect('student_my_classes')


def _notify_class_teachers(classroom, student, is_re_request=False):
    """Create a Notification for teachers, HoD, and HoI of the classroom."""
    action = 're-requested' if is_re_request else 'requested'
    notified_ids = set()

    # Notify class teachers
    for teacher in classroom.teachers.all():
        Notification.objects.create(
            user=teacher,
            message=(
                f'{student.username} has {action} to join '
                f'"{classroom.name}" ({classroom.code}).'
            ),
            notification_type='enrollment_request',
            link='/teacher/enrollment-requests/',
        )
        notified_ids.add(teacher.id)

    # Notify HoD of the class's department
    if classroom.department_id:
        dept = Department.objects.select_related('head').filter(
            id=classroom.department_id, head__isnull=False, is_active=True
        ).first()
        if dept and dept.head_id not in notified_ids:
            Notification.objects.create(
                user=dept.head,
                message=(
                    f'{student.username} has {action} to join '
                    f'"{classroom.name}" ({classroom.code}).'
                ),
                notification_type='enrollment_request',
                link='/teacher/enrollment-requests/',
            )
            notified_ids.add(dept.head_id)

    # Notify HoI (school admin)
    if classroom.school_id and classroom.school.admin_id not in notified_ids:
        Notification.objects.create(
            user=classroom.school.admin,
            message=(
                f'{student.username} has {action} to join '
                f'"{classroom.name}" ({classroom.code}).'
            ),
            notification_type='enrollment_request',
            link='/teacher/enrollment-requests/',
        )


class MyClassesView(LoginRequiredMixin, View):
    """Show the student's enrolled classes and any pending enrollment requests."""

    def get(self, request):
        # Classes the student is already a full member of
        enrolled_entries = (
            ClassStudent.objects.filter(student=request.user)
            .select_related('classroom', 'classroom__subject')
            .order_by('classroom__name')
        )

        # Pending (and recently rejected) enrollment requests
        pending_enrollments = (
            Enrollment.objects.filter(
                student=request.user,
                status='pending',
            )
            .select_related('classroom', 'classroom__subject')
            .order_by('-requested_at')
        )

        return render(request, 'student/my_classes.html', {
            'enrolled_entries': enrolled_entries,
            'pending_enrollments': pending_enrollments,
        })


class StudentClassDetailView(LoginRequiredMixin, View):
    """Show a single class's detail from the student's perspective."""

    def get(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, is_active=True)

        # Verify the student is enrolled in this class
        if not ClassStudent.objects.filter(
            classroom=classroom, student=request.user
        ).exists():
            messages.error(
                request, 'You are not enrolled in this class.'
            )
            return redirect('student_my_classes')

        # Fetch sessions for this class, most recent first
        sessions = (
            ClassSession.objects.filter(classroom=classroom)
            .order_by('-date', '-start_time')
        )

        # Fetch this student's attendance records for every session in the class
        attendance_records = (
            StudentAttendance.objects.filter(
                session__classroom=classroom,
                student=request.user,
            )
            .select_related('session')
            .order_by('-session__date', '-session__start_time')
        )

        # Build a lookup: session_id -> attendance record for template convenience
        attendance_by_session = {
            record.session_id: record for record in attendance_records
        }

        # Compute simple attendance summary
        total_sessions = sessions.filter(status='completed').count()
        present_count = attendance_records.filter(
            status='present', session__status='completed'
        ).count()
        late_count = attendance_records.filter(
            status='late', session__status='completed'
        ).count()
        absent_count = attendance_records.filter(
            status='absent', session__status='completed'
        ).count()

        # Combine sessions with their attendance records for template access
        sessions_with_attendance = []
        for session in sessions:
            att = attendance_by_session.get(session.id)
            sessions_with_attendance.append({
                'session': session,
                'attendance': att,
            })

        return render(request, 'student/class_detail.html', {
            'classroom': classroom,
            'sessions_with_attendance': sessions_with_attendance,
            'total_sessions': total_sessions,
            'present_count': present_count,
            'late_count': late_count,
            'absent_count': absent_count,
        })


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

        # Verify the student is enrolled in this class
        if not ClassStudent.objects.filter(
            classroom=session.classroom, student=request.user
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

class EnrollGlobalClassView(RoleRequiredMixin, View):
    """Auto-enroll a student in a global (school=None) class."""
    required_roles = [Role.STUDENT, Role.INDIVIDUAL_STUDENT]

    def post(self, request, class_id):
        classroom = get_object_or_404(
            ClassRoom, id=class_id, school__isnull=True, is_active=True,
        )

        # Already enrolled?
        if ClassStudent.objects.filter(
            classroom=classroom, student=request.user,
        ).exists():
            messages.info(request, f'You are already enrolled in "{classroom.name}".')
            return redirect('subjects_hub')

        # Auto-enroll (no approval needed for global classes)
        ClassStudent.objects.create(classroom=classroom, student=request.user)
        messages.success(request, f'You have been enrolled in "{classroom.name}".')
        return redirect('subjects_hub')
