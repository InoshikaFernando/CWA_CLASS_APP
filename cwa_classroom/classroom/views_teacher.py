from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from accounts.models import Role
from billing.mixins import ModuleRequiredMixin
from billing.models import ModuleSubscription
from .views import RoleRequiredMixin
from .notifications import create_notification
from .models import (
    School, SchoolTeacher, ClassRoom, ClassTeacher,
    Enrollment, Notification,
    ClassStudent, Department, SchoolStudent,
    ProgressCriteria, ProgressRecord,
)
from attendance.models import ClassSession, StudentAttendance, TeacherAttendance
from .views_progress import _build_hierarchical_criteria


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


def _user_can_access_classroom(user, classroom):
    """
    Check whether *user* may manage sessions / attendance for *classroom*.

    Access is granted when the user is:
      • a ClassTeacher of the classroom, OR
      • the head of the department the classroom belongs to, OR
      • an HoD of any department in the classroom's school, OR
      • the school admin (HoI / Institute Owner), OR
      • has HoI / Institute Owner role and belongs to the school.
    """
    if ClassTeacher.objects.filter(classroom=classroom, teacher=user).exists():
        return True
    if classroom.department_id and classroom.department.head_id == user.id:
        return True
    # HoD of any department in the same school
    if classroom.school_id and Department.objects.filter(
        school=classroom.school, head=user, is_active=True,
    ).exists():
        return True
    if classroom.school_id and classroom.school.admin_id == user.id:
        return True
    # HoI / Institute Owner who belongs to the school
    if classroom.school_id and (
        user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER)
    ) and SchoolTeacher.objects.filter(
        school=classroom.school, teacher=user, is_active=True,
    ).exists():
        return True
    return False


def _is_admin_viewer(user, classroom):
    """
    True when *user* is accessing *classroom* in a supervisory capacity
    (HoD of the classroom's department or school admin / HoI), even if
    they are also a direct class teacher.
    """
    is_class_teacher = ClassTeacher.objects.filter(
        classroom=classroom, teacher=user,
    ).exists()
    if not is_class_teacher:
        return True  # only reached this point via HoD/HoI access
    # User IS a class teacher but might also be HoD or HoI
    if classroom.department_id and classroom.department.head_id == user.id:
        return True
    if classroom.school_id and classroom.school.admin_id == user.id:
        return True
    return False


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

        classes = _get_teacher_classes(request.user, current_school)

        # Pending enrollment requests for the teacher's classes in this school
        pending_count = Enrollment.objects.filter(
            classroom__in=classes,
            status='pending',
        ).count()

        # Pending attendance approvals
        pending_attendance_count = StudentAttendance.objects.filter(
            self_reported=True,
            approved_by__isnull=True,
            session__classroom__in=classes,
        ).count()

        # Upcoming sessions in the next 7 days
        today = timezone.localdate()
        week_ahead = today + timedelta(days=7)
        upcoming_sessions = ClassSession.objects.filter(
            classroom__in=classes,
            date__gte=today,
            date__lte=week_ahead,
            status='scheduled',
        ).select_related('classroom').order_by('date', 'start_time')

        # Today's sessions per class (for Start Session feature)
        todays_sessions = {}
        for session in ClassSession.objects.filter(
            classroom__in=classes, date=today
        ).select_related('classroom'):
            todays_sessions[session.classroom_id] = session

        # Build session status for each class
        class_session_info = []
        for cls in classes:
            session = todays_sessions.get(cls.id)
            if session and session.status == 'scheduled':
                # Active session — show "Continue" link
                class_session_info.append({
                    'classroom': cls,
                    'session': session,
                    'status': 'active',
                })
            elif session and session.status == 'completed':
                class_session_info.append({
                    'classroom': cls,
                    'session': session,
                    'status': 'completed',
                })
            else:
                # No session today or cancelled — can start
                class_session_info.append({
                    'classroom': cls,
                    'session': None,
                    'status': 'can_start',
                })

        return render(request, 'teacher/dashboard.html', {
            'schools': SchoolTeacher.objects.filter(
                teacher=request.user, is_active=True
            ).select_related('school'),
            'current_school': current_school,
            'classes': classes,
            'pending_count': pending_count,
            'pending_attendance_count': pending_attendance_count,
            'upcoming_sessions': upcoming_sessions,
            'class_session_info': class_session_info,
        })


# ---------------------------------------------------------------------------
# 2. SchoolSwitcherView
# ---------------------------------------------------------------------------

class SchoolSwitcherView(LoginRequiredMixin, View):
    """Switch active school for multi-school users (teachers, students, HoI)."""

    def post(self, request):
        school_id = request.POST.get('school_id')
        if school_id:
            from billing.entitlements import get_all_schools_for_user
            # Validate user belongs to this school (any role)
            allowed_ids = set(
                get_all_schools_for_user(request.user).values_list('id', flat=True)
            )
            if int(school_id) in allowed_ids:
                request.session['current_school_id'] = int(school_id)
            else:
                messages.error(request, 'You are not a member of that school.')
        referer = request.META.get('HTTP_REFERER', '')
        return redirect(referer or 'subjects_hub')


# ---------------------------------------------------------------------------
# 3. EnrollmentRequestsView
# ---------------------------------------------------------------------------

class EnrollmentRequestsView(RoleRequiredMixin, View):
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
        Role.JUNIOR_TEACHER,
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
        Role.JUNIOR_TEACHER,
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
        # (reactivate if previously removed)
        cs, created = ClassStudent.objects.get_or_create(
            classroom=enrollment.classroom,
            student=enrollment.student,
        )
        if not created and not cs.is_active:
            cs.is_active = True
            cs.save(update_fields=['is_active'])

        # Auto-create SchoolStudent link when class belongs to a school
        if enrollment.classroom.school_id:
            # Check student limit before adding to school
            from billing.entitlements import check_student_limit
            is_existing = SchoolStudent.objects.filter(
                school=enrollment.classroom.school,
                student=enrollment.student,
            ).exists()
            if not is_existing:
                allowed, current, limit = check_student_limit(enrollment.classroom.school)
                if not allowed:
                    messages.warning(
                        request,
                        f'Student added to class but school student limit ({limit}) reached. '
                        f'Please upgrade your plan.',
                    )
            SchoolStudent.objects.get_or_create(
                school=enrollment.classroom.school,
                student=enrollment.student,
            )

        # Notify the student
        create_notification(
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
        Role.JUNIOR_TEACHER,
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

        create_notification(
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
# Attendance & session views moved to attendance app (CPP-64)
# ---------------------------------------------------------------------------
