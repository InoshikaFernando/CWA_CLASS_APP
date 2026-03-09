from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from accounts.models import Role
from .views import RoleRequiredMixin
from .models import (
    School, SchoolTeacher, ClassRoom, ClassSession, ClassTeacher,
    Enrollment, StudentAttendance, TeacherAttendance, Notification,
    ClassStudent, Department, SchoolStudent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_teacher_current_school(request):
    """
    Return the current School for the logged-in teacher.

    1. Try the school_id stored in the session.
    2. Fall back to the first school the teacher belongs to via SchoolTeacher.
    3. Return None if the teacher has no school memberships.
    """
    school_id = request.session.get('current_school_id')
    if school_id:
        try:
            membership = SchoolTeacher.objects.select_related('school').get(
                school_id=school_id,
                teacher=request.user,
                is_active=True,
            )
            return membership.school
        except SchoolTeacher.DoesNotExist:
            # Stale session value -- clear it and fall through
            request.session.pop('current_school_id', None)

    # Fall back to the first active school membership
    membership = (
        SchoolTeacher.objects
        .filter(teacher=request.user, is_active=True)
        .select_related('school')
        .first()
    )
    if membership:
        request.session['current_school_id'] = membership.school_id
        return membership.school

    return None


def _get_teacher_classes(teacher, school):
    """Return ClassRooms in *school* where *teacher* is assigned."""
    return ClassRoom.objects.filter(
        school=school,
        class_teachers__teacher=teacher,
        is_active=True,
    ).distinct()


def _can_manage_enrollment(user, classroom):
    """Check if user can approve/reject enrollments for this classroom."""
    # Teacher of the class
    if ClassTeacher.objects.filter(classroom=classroom, teacher=user).exists():
        return True
    # HoD of the class's department
    if classroom.department_id:
        if Department.objects.filter(id=classroom.department_id, head=user, is_active=True).exists():
            return True
    # HoI / school admin
    if classroom.school_id and classroom.school.admin == user:
        return True
    return False


def _get_managed_classes(user, school):
    """Return classrooms the user can manage enrollments for, based on role.
    - HoI/Owner: all classes in their school
    - HoD: classes in their departments + classes they teach
    - Teacher: classes they teach
    """
    if school.admin == user:
        return ClassRoom.objects.filter(school=school, is_active=True)

    # HoD — classes in departments they head + classes they teach
    dept_ids = Department.objects.filter(
        school=school, head=user, is_active=True
    ).values_list('id', flat=True)

    if dept_ids:
        return ClassRoom.objects.filter(
            Q(department_id__in=dept_ids) | Q(class_teachers__teacher=user),
            school=school,
            is_active=True,
        ).distinct()

    # Regular teacher
    return _get_teacher_classes(user, school)


# ---------------------------------------------------------------------------
# 1. TeacherDashboardView
# ---------------------------------------------------------------------------

class TeacherDashboardView(RoleRequiredMixin, View):
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def get(self, request):
        current_school = _get_teacher_current_school(request)

        # All schools the teacher belongs to (for the school-switcher dropdown)
        teacher_schools = School.objects.filter(
            school_teachers__teacher=request.user,
            school_teachers__is_active=True,
        ).distinct()

        if not current_school:
            return render(request, 'teacher/dashboard.html', {
                'teacher_schools': teacher_schools,
                'current_school': None,
                'my_classes': ClassRoom.objects.none(),
                'pending_enrollment_count': 0,
                'upcoming_sessions': ClassSession.objects.none(),
            })

        my_classes = _get_teacher_classes(request.user, current_school)

        # Pending enrollment requests for the teacher's classes in this school
        pending_enrollment_count = Enrollment.objects.filter(
            classroom__in=my_classes,
            status='pending',
        ).count()

        # Pending attendance approvals
        pending_attendance_count = StudentAttendance.objects.filter(
            self_reported=True,
            approved_by__isnull=True,
            session__classroom__in=my_classes,
        ).count()

        # Upcoming sessions in the next 7 days
        today = timezone.localdate()
        week_ahead = today + timedelta(days=7)
        upcoming_sessions = ClassSession.objects.filter(
            classroom__in=my_classes,
            date__gte=today,
            date__lte=week_ahead,
            status='scheduled',
        ).select_related('classroom').order_by('date', 'start_time')

        return render(request, 'teacher/dashboard.html', {
            'teacher_schools': teacher_schools,
            'current_school': current_school,
            'my_classes': my_classes,
            'pending_enrollment_count': pending_enrollment_count,
            'pending_attendance_count': pending_attendance_count,
            'upcoming_sessions': upcoming_sessions,
        })


# ---------------------------------------------------------------------------
# 2. SchoolSwitcherView
# ---------------------------------------------------------------------------

class SchoolSwitcherView(RoleRequiredMixin, View):
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def post(self, request):
        school_id = request.POST.get('school_id')
        if school_id:
            # Validate the teacher actually belongs to this school
            exists = SchoolTeacher.objects.filter(
                school_id=school_id,
                teacher=request.user,
                is_active=True,
            ).exists()
            if exists:
                request.session['current_school_id'] = int(school_id)
            else:
                messages.error(request, 'You are not a member of that school.')
        return redirect('teacher_dashboard')


# ---------------------------------------------------------------------------
# 3. EnrollmentRequestsView
# ---------------------------------------------------------------------------

class EnrollmentRequestsView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
    ]

    def get(self, request):
        # HoI may not be in SchoolTeacher — fall back to School.admin
        current_school = _get_teacher_current_school(request)
        if not current_school:
            current_school = School.objects.filter(admin=request.user).first()
        if not current_school:
            messages.warning(request, 'Please select a school first.')
            return redirect('teacher_dashboard')

        managed_classes = _get_managed_classes(request.user, current_school)
        pending_enrollments = (
            Enrollment.objects
            .filter(classroom__in=managed_classes, status='pending')
            .select_related('classroom', 'student')
            .order_by('-requested_at')
        )

        return render(request, 'teacher/enrollment_requests.html', {
            'current_school': current_school,
            'pending_enrollments': pending_enrollments,
        })


# ---------------------------------------------------------------------------
# 4. EnrollmentApproveView
# ---------------------------------------------------------------------------

class EnrollmentApproveView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
    ]

    def post(self, request, enrollment_id):
        enrollment = get_object_or_404(Enrollment, id=enrollment_id, status='pending')

        if not _can_manage_enrollment(request.user, enrollment.classroom):
            messages.error(request, 'You do not have permission to approve this enrollment.')
            return redirect('enrollment_requests')

        # Approve the enrollment
        enrollment.status = 'approved'
        enrollment.approved_at = timezone.now()
        enrollment.approved_by = request.user
        enrollment.save()

        # Create ClassStudent entry so the student is actually in the class
        ClassStudent.objects.get_or_create(
            classroom=enrollment.classroom,
            student=enrollment.student,
        )

        # Auto-create SchoolStudent link when class belongs to a school
        if enrollment.classroom.school_id:
            SchoolStudent.objects.get_or_create(
                school=enrollment.classroom.school,
                student=enrollment.student,
            )

        # Notify the student
        Notification.objects.create(
            user=enrollment.student,
            message=f'Your enrollment in "{enrollment.classroom.name}" has been approved.',
            notification_type='enrollment_approved',
        )

        messages.success(
            request,
            f'{enrollment.student.username} has been approved for {enrollment.classroom.name}.',
        )
        return redirect('enrollment_requests')


# ---------------------------------------------------------------------------
# 5. EnrollmentRejectView
# ---------------------------------------------------------------------------

class EnrollmentRejectView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
    ]

    def post(self, request, enrollment_id):
        enrollment = get_object_or_404(Enrollment, id=enrollment_id, status='pending')

        if not _can_manage_enrollment(request.user, enrollment.classroom):
            messages.error(request, 'You do not have permission to reject this enrollment.')
            return redirect('enrollment_requests')

        # Reject the enrollment
        reason = request.POST.get('rejection_reason', '').strip()
        enrollment.status = 'rejected'
        enrollment.rejection_reason = reason
        enrollment.save()

        # Notify the student
        notification_message = (
            f'Your enrollment in "{enrollment.classroom.name}" has been declined.'
        )
        if reason:
            notification_message += f' Reason: {reason}'

        Notification.objects.create(
            user=enrollment.student,
            message=notification_message,
            notification_type='enrollment_rejected',
        )

        messages.success(
            request,
            f'{enrollment.student.username} has been rejected from {enrollment.classroom.name}.',
        )
        return redirect('enrollment_requests')


# ---------------------------------------------------------------------------
# 6. SessionAttendanceView
# ---------------------------------------------------------------------------

class SessionAttendanceView(RoleRequiredMixin, View):
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def get(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom'),
            id=session_id,
        )

        # Verify the teacher is assigned to this class
        is_teacher_of_class = ClassTeacher.objects.filter(
            classroom=session.classroom,
            teacher=request.user,
        ).exists()
        if not is_teacher_of_class:
            messages.error(request, 'You are not assigned to this class.')
            return redirect('teacher_dashboard')

        # All enrolled students for this classroom
        enrolled_students = session.classroom.students.all().order_by(
            'last_name', 'first_name', 'username',
        )

        # Existing attendance records for this session (for pre-filling the form)
        existing_records = {}
        for sa in StudentAttendance.objects.filter(session=session):
            existing_records[sa.student_id] = {
                'status': sa.status,
                'self_reported': sa.self_reported,
                'approved_by': sa.approved_by,
            }

        students_with_status = []
        for student in enrolled_students:
            record = existing_records.get(student.id, {})
            students_with_status.append({
                'student': student,
                'current_status': record.get('status', ''),
                'self_reported': record.get('self_reported', False),
                'approved': record.get('approved_by') is not None,
            })

        return render(request, 'teacher/session_attendance.html', {
            'session': session,
            'classroom': session.classroom,
            'students_with_status': students_with_status,
        })

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom'),
            id=session_id,
        )

        # Verify the teacher is assigned to this class
        is_teacher_of_class = ClassTeacher.objects.filter(
            classroom=session.classroom,
            teacher=request.user,
        ).exists()
        if not is_teacher_of_class:
            messages.error(request, 'You are not assigned to this class.')
            return redirect('teacher_dashboard')

        enrolled_students = session.classroom.students.all()
        saved_count = 0

        for student in enrolled_students:
            status = request.POST.get(f'status_{student.id}', '').strip()
            if status not in ('present', 'absent', 'late'):
                continue

            StudentAttendance.objects.update_or_create(
                session=session,
                student=student,
                defaults={
                    'status': status,
                    'marked_by': request.user,
                    'self_reported': False,
                    'approved_by': None,
                    'approved_at': None,
                },
            )
            saved_count += 1

        messages.success(request, f'Attendance saved for {saved_count} student(s).')
        return redirect('session_attendance', session_id=session_id)


# ---------------------------------------------------------------------------
# 7. TeacherSelfAttendanceView
# ---------------------------------------------------------------------------

class TeacherSelfAttendanceView(RoleRequiredMixin, View):
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom'),
            id=session_id,
        )

        # Verify the teacher is assigned to this class
        is_teacher_of_class = ClassTeacher.objects.filter(
            classroom=session.classroom,
            teacher=request.user,
        ).exists()
        if not is_teacher_of_class:
            messages.error(request, 'You are not assigned to this class.')
            return redirect('teacher_dashboard')

        status = request.POST.get('status', 'present').strip()
        if status not in ('present', 'absent'):
            status = 'present'

        TeacherAttendance.objects.update_or_create(
            session=session,
            teacher=request.user,
            defaults={
                'status': status,
                'self_reported': True,
            },
        )

        messages.success(request, f'Your attendance for {session} has been recorded.')

        # Redirect back to the referring page, or fall back to the dashboard
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        if next_url:
            return redirect(next_url)
        return redirect('teacher_dashboard')


# ---------------------------------------------------------------------------
# 8. Student Attendance Approval Views
# ---------------------------------------------------------------------------

class StudentAttendanceApprovalListView(RoleRequiredMixin, View):
    """List self-reported student attendance records pending teacher approval."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def get(self, request):
        current_school = _get_teacher_current_school(request)
        if not current_school:
            messages.warning(request, 'Please select a school first.')
            return redirect('teacher_dashboard')

        my_classes = _get_teacher_classes(request.user, current_school)

        pending_records = (
            StudentAttendance.objects.filter(
                self_reported=True,
                approved_by__isnull=True,
                session__classroom__in=my_classes,
            )
            .select_related('session', 'session__classroom', 'student')
            .order_by('-session__date', '-session__start_time', 'student__last_name')
        )

        # Group by session for the template
        sessions_dict = {}
        for record in pending_records:
            sid = record.session_id
            if sid not in sessions_dict:
                sessions_dict[sid] = {
                    'session': record.session,
                    'records': [],
                }
            sessions_dict[sid]['records'].append(record)

        grouped_sessions = list(sessions_dict.values())

        return render(request, 'teacher/attendance_approvals.html', {
            'current_school': current_school,
            'grouped_sessions': grouped_sessions,
            'total_pending': pending_records.count(),
        })


class StudentAttendanceApproveView(RoleRequiredMixin, View):
    """Approve a single self-reported student attendance record."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def post(self, request, attendance_id):
        record = get_object_or_404(
            StudentAttendance.objects.select_related('session__classroom'),
            id=attendance_id,
            self_reported=True,
            approved_by__isnull=True,
        )

        # Verify teacher is assigned to this class
        if not ClassTeacher.objects.filter(
            classroom=record.session.classroom, teacher=request.user
        ).exists():
            messages.error(request, 'You are not assigned to this class.')
            return redirect('attendance_approvals')

        record.approved_by = request.user
        record.approved_at = timezone.now()
        record.save(update_fields=['approved_by', 'approved_at'])

        messages.success(
            request,
            f'Approved attendance for {record.student.get_full_name() or record.student.username}.'
        )
        return redirect('attendance_approvals')


class StudentAttendanceRejectView(RoleRequiredMixin, View):
    """Reject (delete) a self-reported student attendance record so they can re-mark."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def post(self, request, attendance_id):
        record = get_object_or_404(
            StudentAttendance.objects.select_related('session__classroom'),
            id=attendance_id,
            self_reported=True,
            approved_by__isnull=True,
        )

        # Verify teacher is assigned to this class
        if not ClassTeacher.objects.filter(
            classroom=record.session.classroom, teacher=request.user
        ).exists():
            messages.error(request, 'You are not assigned to this class.')
            return redirect('attendance_approvals')

        student_name = record.student.get_full_name() or record.student.username
        record.delete()

        messages.success(request, f'Rejected attendance for {student_name}.')
        return redirect('attendance_approvals')


class StudentAttendanceBulkApproveView(RoleRequiredMixin, View):
    """Bulk approve all pending self-reported records for a session."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def post(self, request):
        session_id = request.POST.get('session_id')
        if not session_id:
            messages.error(request, 'No session specified.')
            return redirect('attendance_approvals')

        session = get_object_or_404(
            ClassSession.objects.select_related('classroom'),
            id=session_id,
        )

        # Verify teacher is assigned to this class
        if not ClassTeacher.objects.filter(
            classroom=session.classroom, teacher=request.user
        ).exists():
            messages.error(request, 'You are not assigned to this class.')
            return redirect('attendance_approvals')

        count = StudentAttendance.objects.filter(
            session=session,
            self_reported=True,
            approved_by__isnull=True,
        ).update(
            approved_by=request.user,
            approved_at=timezone.now(),
        )

        messages.success(request, f'Approved {count} attendance record(s) for {session}.')
        return redirect('attendance_approvals')
