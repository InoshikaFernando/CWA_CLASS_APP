from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone

from accounts.models import Role
from billing.mixins import ModuleRequiredMixin
from billing.models import ModuleSubscription
from .views import RoleRequiredMixin
from .notifications import create_notification
from .models import (
    ClassRoom, ClassStudent, Enrollment,
    Notification, Department,
)
from attendance.models import ClassSession, StudentAttendance


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

        # Check if student is already an active member of this class
        if ClassStudent.objects.filter(
            classroom=classroom, student=request.user, is_active=True,
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
            elif existing_enrollment.status in ('rejected', 'removed'):
                # Allow re-requesting after rejection/removal: reset to pending
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
        create_notification(
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
            create_notification(
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
        create_notification(
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
        # Classes the student is already an active member of
        enrolled_entries = (
            ClassStudent.objects.filter(student=request.user, is_active=True)
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

        # Verify the student is actively enrolled in this class
        if not ClassStudent.objects.filter(
            classroom=classroom, student=request.user, is_active=True,
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


# StudentAttendanceHistoryView and StudentSelfMarkAttendanceView moved to
# attendance/views_student.py (CPP-64)


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
            classroom=classroom, student=request.user, is_active=True,
        ).exists():
            messages.info(request, f'You are already enrolled in "{classroom.name}".')
            return redirect('subjects_hub')

        # Auto-enroll (no approval needed for global classes) — reactivate if previously removed
        cs, created = ClassStudent.objects.get_or_create(
            classroom=classroom, student=request.user,
            defaults={'is_active': True},
        )
        if not created and not cs.is_active:
            cs.is_active = True
            cs.save(update_fields=['is_active'])
        messages.success(request, f'You have been enrolled in "{classroom.name}".')
        return redirect('subjects_hub')
