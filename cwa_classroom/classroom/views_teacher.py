from datetime import timedelta

from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from accounts.models import Role
from audit.services import log_event
from billing.mixins import ModuleRequiredMixin
from billing.models import ModuleSubscription
from .views import RoleRequiredMixin
from .notifications import create_notification
from .models import (
    School, SchoolTeacher, ClassRoom, ClassSession, ClassTeacher,
    Enrollment, StudentAttendance, TeacherAttendance, Notification,
    ClassStudent, Department, SchoolStudent,
    ProgressCriteria, ProgressRecord, ParentLinkRequest, ParentStudent,
    SchoolHoliday, PublicHoliday,
)
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

        # Upcoming sessions in the next 7 days, excluding holidays
        from django.db.models import Exists, OuterRef
        today = timezone.localdate()
        week_ahead = today + timedelta(days=7)
        upcoming_sessions = ClassSession.objects.filter(
            classroom__in=classes,
            date__gte=today,
            date__lte=week_ahead,
            status='scheduled',
        ).exclude(
            Exists(SchoolHoliday.objects.filter(
                school=OuterRef('classroom__school'),
                start_date__lte=OuterRef('date'),
                end_date__gte=OuterRef('date'),
            ))
        ).exclude(
            Exists(PublicHoliday.objects.filter(
                school=OuterRef('classroom__school'),
                date=OuterRef('date'),
            ))
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
                switched_school = School.objects.filter(id=int(school_id)).first()
                if switched_school:
                    log_event(
                        user=request.user,
                        school=switched_school,
                        category='data_change',
                        action='school_switched',
                        detail={'school_id': int(school_id), 'school': str(switched_school)},
                        request=request,
                    )
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
        paginator = Paginator(pending_enrollments, 25)
        page = paginator.get_page(request.GET.get('page'))

        return render(request, 'teacher/enrollment_requests.html', {
            'current_school': current_school,
            'pending_enrollments': page,
            'page': page,
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
            link=reverse('student_class_detail', kwargs={'class_id': enrollment.classroom_id}),
        )

        log_event(
            user=request.user,
            school=enrollment.classroom.school if enrollment.classroom.school_id else None,
            category='data_change',
            action='enrollment_approved',
            detail={'enrollment_id': enrollment.id,
                    'student_id': enrollment.student_id,
                    'student': enrollment.student.username,
                    'classroom_id': enrollment.classroom_id,
                    'classroom': enrollment.classroom.name},
            request=request,
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
            link=reverse('student_join_class'),
        )

        log_event(
            user=request.user,
            school=enrollment.classroom.school if enrollment.classroom.school_id else None,
            category='data_change',
            action='enrollment_rejected',
            detail={'enrollment_id': enrollment.id,
                    'student_id': enrollment.student_id,
                    'student': enrollment.student.username,
                    'classroom_id': enrollment.classroom_id,
                    'classroom': enrollment.classroom.name,
                    'reason': reason},
            request=request,
        )
        messages.success(
            request,
            f'{enrollment.student.username} has been rejected from {enrollment.classroom.name}.',
        )
        return redirect('enrollment_requests')


# ---------------------------------------------------------------------------
# 6. SessionAttendanceView
# ---------------------------------------------------------------------------

class SessionAttendanceView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def _get_progress_context(self, session, enrolled_students):
        """Build progress criteria + rows for the session attendance template."""
        classroom = session.classroom

        # Get approved criteria matching this classroom's school + subject + levels
        criteria_qs = ProgressCriteria.objects.filter(
            school=classroom.school,
            status='approved',
        )
        if classroom.subject:
            criteria_qs = criteria_qs.filter(subject=classroom.subject)
        if classroom.levels.exists():
            criteria_qs = criteria_qs.filter(
                Q(level__in=classroom.levels.all()) | Q(level__isnull=True)
            )

        criteria_qs = criteria_qs.select_related('subject', 'level', 'parent').order_by(
            'subject__name', 'level__level_number', 'order', 'name',
        )
        criteria_list = list(criteria_qs)
        if not criteria_list:
            return {}

        hierarchical_criteria = _build_hierarchical_criteria(criteria_list)

        # Check for existing progress records for THIS session
        existing_progress = {}
        for pr in ProgressRecord.objects.filter(session=session, student__in=enrolled_students):
            existing_progress[(pr.student_id, pr.criteria_id)] = pr.status

        # If no progress records exist for this session, auto-load from
        # the most recent PREVIOUS completed session of the same classroom
        auto_loaded = False
        if not existing_progress:
            previous_session = (
                ClassSession.objects
                .filter(classroom=classroom, status='completed', date__lt=session.date)
                .order_by('-date', '-start_time')
                .first()
            )
            if not previous_session:
                # Also try sessions on the same date but earlier
                previous_session = (
                    ClassSession.objects
                    .filter(classroom=classroom, status='completed')
                    .exclude(pk=session.pk)
                    .order_by('-date', '-start_time')
                    .first()
                )
            if previous_session:
                prev_records = ProgressRecord.objects.filter(
                    session=previous_session,
                    student__in=enrolled_students,
                    criteria__in=criteria_qs,
                )
                for pr in prev_records:
                    existing_progress[(pr.student_id, pr.criteria_id)] = pr.status
                auto_loaded = bool(prev_records.exists() if hasattr(prev_records, 'exists') else prev_records)

        # Build progress rows for the template
        progress_rows = []
        for student in enrolled_students:
            criteria_statuses = []
            for h_item in hierarchical_criteria:
                crit = h_item['criteria']
                current_status = existing_progress.get((student.id, crit.id), 'not_started')
                criteria_statuses.append({
                    'criteria': crit,
                    'is_child': h_item['is_child'],
                    'current_status': current_status,
                })
            progress_rows.append({
                'student': student,
                'criteria_statuses': criteria_statuses,
            })

        return {
            'hierarchical_criteria': hierarchical_criteria,
            'progress_rows': progress_rows,
            'progress_status_choices': ProgressRecord.STATUS_CHOICES,
            'auto_loaded': auto_loaded,
        }

    def get(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__department', 'classroom__school'),
            id=session_id,
        )

        if not _user_can_access_classroom(request.user, session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('teacher_dashboard')

        # All active enrolled students for this classroom
        from accounts.models import CustomUser
        active_ids = ClassStudent.objects.filter(
            classroom=session.classroom, is_active=True,
        ).values_list('student_id', flat=True)
        enrolled_students = list(CustomUser.objects.filter(id__in=active_ids).order_by(
            'last_name', 'first_name', 'username',
        ))

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

        # Teacher's own attendance for this session
        teacher_attendance = TeacherAttendance.objects.filter(
            session=session, teacher=request.user,
        ).first()

        # --- Admin viewer (HoD / HoI): load all class teachers ---
        admin_viewer = _is_admin_viewer(request.user, session.classroom)
        teacher_attendance_rows = []
        if admin_viewer:
            class_teachers = list(
                ClassTeacher.objects.filter(classroom=session.classroom)
                .select_related('teacher')
                .order_by('teacher__last_name', 'teacher__first_name')
            )
            existing_teacher_att = {
                ta.teacher_id: ta
                for ta in TeacherAttendance.objects.filter(session=session)
            }
            for ct in class_teachers:
                ta = existing_teacher_att.get(ct.teacher_id)
                teacher_attendance_rows.append({
                    'teacher': ct.teacher,
                    'current_status': ta.status if ta else '',
                    'is_current_user': ct.teacher_id == request.user.id,
                })

        # Progress tracking context
        progress_ctx = self._get_progress_context(session, enrolled_students)

        ctx = {
            'session': session,
            'classroom': session.classroom,
            'students_with_status': students_with_status,
            'teacher_attendance': teacher_attendance,
            'is_admin_viewer': admin_viewer,
            'teacher_attendance_rows': teacher_attendance_rows,
        }
        ctx.update(progress_ctx)
        return render(request, 'teacher/session_attendance.html', ctx)

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__department', 'classroom__school'),
            id=session_id,
        )

        if not _user_can_access_classroom(request.user, session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('teacher_dashboard')

        from accounts.models import CustomUser
        active_ids = ClassStudent.objects.filter(
            classroom=session.classroom, is_active=True,
        ).values_list('student_id', flat=True)
        enrolled_students = list(CustomUser.objects.filter(id__in=active_ids))
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

        # ----- Save Progress Records -----
        classroom = session.classroom
        criteria_qs = ProgressCriteria.objects.filter(
            school=classroom.school,
            status='approved',
        )
        if classroom.subject:
            criteria_qs = criteria_qs.filter(subject=classroom.subject)
        if classroom.levels.exists():
            criteria_qs = criteria_qs.filter(
                Q(level__in=classroom.levels.all()) | Q(level__isnull=True)
            )

        valid_progress_statuses = {s[0] for s in ProgressRecord.STATUS_CHOICES}
        progress_saved = 0

        for student in enrolled_students:
            for crit in criteria_qs:
                field_name = f'progress_{student.id}_{crit.id}'
                new_status = request.POST.get(field_name, '').strip()

                if new_status not in valid_progress_statuses:
                    continue

                ProgressRecord.objects.update_or_create(
                    student=student,
                    criteria=crit,
                    session=session,
                    defaults={
                        'status': new_status,
                        'recorded_by': request.user,
                    },
                )
                progress_saved += 1

        # --- Save teacher attendance ---
        admin_viewer = _is_admin_viewer(request.user, session.classroom)
        if admin_viewer:
            # HoD / HoI mode: save attendance for each class teacher
            class_teacher_ids = list(
                ClassTeacher.objects.filter(classroom=session.classroom)
                .values_list('teacher_id', flat=True)
            )
            for teacher_id in class_teacher_ids:
                status = request.POST.get(f'teacher_att_{teacher_id}', '').strip()
                if status in ('present', 'absent'):
                    TeacherAttendance.objects.update_or_create(
                        session=session,
                        teacher_id=teacher_id,
                        defaults={
                            'status': status,
                            'self_reported': False,
                            'approved_by': request.user,
                            'approved_at': timezone.now(),
                        },
                    )
        else:
            # Regular teacher mode: save own attendance only
            teacher_status = request.POST.get('teacher_status', '').strip()
            if teacher_status in ('present', 'absent'):
                TeacherAttendance.objects.update_or_create(
                    session=session,
                    teacher=request.user,
                    defaults={
                        'status': teacher_status,
                        'self_reported': False,
                    },
                )

        log_event(
            user=request.user,
            school=session.classroom.school,
            category='data_change',
            action='session_attendance_saved',
            detail={
                'session_id': session.id,
                'classroom_id': session.classroom_id,
                'classroom': session.classroom.name,
                'student_attendance_saved': saved_count,
                'progress_saved': progress_saved,
            },
            request=request,
        )

        # Optionally complete the session
        complete_session = request.POST.get('complete_session') == 'on'
        if complete_session and session.status == 'scheduled':
            session.status = 'completed'
            session.save(update_fields=['status'])
            msg = f'Attendance saved for {saved_count} student(s).'
            if progress_saved:
                msg += f' Progress saved for {progress_saved} record(s).'
            msg += ' Session marked as completed.'
            messages.success(request, msg)
            return redirect('class_detail', class_id=session.classroom_id)

        msg = f'Attendance saved for {saved_count} student(s).'
        if progress_saved:
            msg += f' Progress saved for {progress_saved} record(s).'
        messages.success(request, msg)
        return redirect('session_attendance', session_id=session_id)


# ---------------------------------------------------------------------------
# 7. TeacherSelfAttendanceView
# ---------------------------------------------------------------------------

class TeacherSelfAttendanceView(RoleRequiredMixin, ModuleRequiredMixin, View):
    required_module = ModuleSubscription.MODULE_TEACHERS_ATTENDANCE
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

        log_event(
            user=request.user,
            school=session.classroom.school,
            category='data_change',
            action='teacher_self_attendance_recorded',
            detail={
                'session_id': session.id,
                'classroom_id': session.classroom_id,
                'classroom': session.classroom.name,
                'status': status,
            },
            request=request,
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

class StudentAttendanceApprovalListView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """List self-reported student attendance records pending teacher approval."""
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

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


class StudentAttendanceApproveView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Approve a single self-reported student attendance record."""
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request, attendance_id):
        record = get_object_or_404(
            StudentAttendance.objects.select_related('session__classroom', 'session__classroom__department', 'session__classroom__school'),
            id=attendance_id,
            self_reported=True,
            approved_by__isnull=True,
        )

        if not _user_can_access_classroom(request.user, record.session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('attendance_approvals')

        record.approved_by = request.user
        record.approved_at = timezone.now()
        record.save(update_fields=['approved_by', 'approved_at'])

        log_event(
            user=request.user,
            school=record.session.classroom.school,
            category='data_change',
            action='student_attendance_approved',
            detail={
                'attendance_id': record.id,
                'student_id': record.student_id,
                'student': record.student.username,
                'session_id': record.session_id,
                'classroom_id': record.session.classroom_id,
                'classroom': record.session.classroom.name,
            },
            request=request,
        )

        messages.success(
            request,
            f'Approved attendance for {record.student.get_full_name() or record.student.username}.'
        )
        return redirect('attendance_approvals')


class StudentAttendanceRejectView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Reject (delete) a self-reported student attendance record so they can re-mark."""
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request, attendance_id):
        record = get_object_or_404(
            StudentAttendance.objects.select_related('session__classroom', 'session__classroom__department', 'session__classroom__school'),
            id=attendance_id,
            self_reported=True,
            approved_by__isnull=True,
        )

        if not _user_can_access_classroom(request.user, record.session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('attendance_approvals')

        student_name = record.student.get_full_name() or record.student.username
        attendance_id = record.id
        student_id = record.student_id
        student_username = record.student.username
        session_id = record.session_id
        classroom_id = record.session.classroom_id
        classroom_name = record.session.classroom.name
        school = record.session.classroom.school

        record.delete()

        log_event(
            user=request.user,
            school=school,
            category='data_change',
            action='student_attendance_rejected',
            detail={
                'attendance_id': attendance_id,
                'student_id': student_id,
                'student': student_username,
                'session_id': session_id,
                'classroom_id': classroom_id,
                'classroom': classroom_name,
            },
            request=request,
        )

        messages.success(request, f'Rejected attendance for {student_name}.')
        return redirect('attendance_approvals')


class StudentAttendanceBulkApproveView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Bulk approve all pending self-reported records for a session."""
    required_module = ModuleSubscription.MODULE_STUDENTS_ATTENDANCE
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request):
        session_id = request.POST.get('session_id')
        if not session_id:
            messages.error(request, 'No session specified.')
            return redirect('attendance_approvals')

        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__department', 'classroom__school'),
            id=session_id,
        )

        if not _user_can_access_classroom(request.user, session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('attendance_approvals')

        count = StudentAttendance.objects.filter(
            session=session,
            self_reported=True,
            approved_by__isnull=True,
        ).update(
            approved_by=request.user,
            approved_at=timezone.now(),
        )

        log_event(
            user=request.user,
            school=session.classroom.school,
            category='data_change',
            action='student_attendance_bulk_approved',
            detail={
                'session_id': session.id,
                'classroom_id': session.classroom_id,
                'classroom': session.classroom.name,
                'count': count,
            },
            request=request,
        )

        messages.success(request, f'Approved {count} attendance record(s) for {session}.')
        return redirect('attendance_approvals')


# ---------------------------------------------------------------------------
# 11. StartSessionView
# ---------------------------------------------------------------------------

class StartSessionView(RoleRequiredMixin, View):
    """One-click: create today's session and go to attendance marking."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, is_active=True)

        if not _user_can_access_classroom(request.user, classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('teacher_dashboard')

        today = timezone.localdate()

        # Check for existing session today
        existing = ClassSession.objects.filter(classroom=classroom, date=today).first()
        if existing:
            if existing.status == 'scheduled':
                return redirect('session_attendance', session_id=existing.id)
            elif existing.status == 'completed':
                messages.info(request, 'A session for today has already been completed.')
                return redirect('class_detail', class_id=class_id)
            # If cancelled, allow creating a new one (fall through)

        now = timezone.localtime().time()
        session = ClassSession.objects.create(
            classroom=classroom,
            date=today,
            start_time=classroom.start_time or now,
            end_time=classroom.end_time or (timezone.localtime() + timedelta(hours=1)).time(),
            status='scheduled',
            created_by=request.user,
        )

        # Auto-mark the starting teacher as present
        TeacherAttendance.objects.get_or_create(
            session=session,
            teacher=request.user,
            defaults={'status': 'present', 'self_reported': False},
        )

        log_event(
            user=request.user,
            school=classroom.school,
            category='data_change',
            action='session_started',
            detail={
                'session_id': session.id,
                'classroom_id': classroom.id,
                'classroom': classroom.name,
                'date': str(today),
            },
            request=request,
        )

        messages.success(request, f'Session started for {classroom.name}.')
        return redirect('session_attendance', session_id=session.id)


# ---------------------------------------------------------------------------
# 11b. DeleteSessionView
# ---------------------------------------------------------------------------

class DeleteSessionView(RoleRequiredMixin, View):
    """Delete a session and all associated attendance/progress records."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__department', 'classroom__school'),
            id=session_id,
        )

        if not _user_can_access_classroom(request.user, session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('teacher_dashboard')

        class_id = session.classroom_id
        classroom_name = session.classroom.name
        school = session.classroom.school
        session_pk = session.id
        session_date = str(session.date)
        session_label = f'{session.date.strftime("%d %b %Y")} ({session.start_time.strftime("%H:%M")}\u2013{session.end_time.strftime("%H:%M")})'

        # Delete related records explicitly, then the session itself
        StudentAttendance.objects.filter(session=session).delete()
        TeacherAttendance.objects.filter(session=session).delete()
        ProgressRecord.objects.filter(session=session).delete()
        session.delete()

        log_event(
            user=request.user,
            school=school,
            category='data_change',
            action='session_deleted',
            detail={
                'session_id': session_pk,
                'classroom_id': class_id,
                'classroom': classroom_name,
                'date': session_date,
            },
            request=request,
        )

        messages.success(request, f'Session on {session_label} and all related records deleted.')
        return redirect('class_detail', class_id=class_id)


# ---------------------------------------------------------------------------
# 12. CreateSessionView
# ---------------------------------------------------------------------------

class CreateSessionView(RoleRequiredMixin, View):
    """Manual session creation form for specific dates/times."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def _get_classroom(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, id=class_id, is_active=True)
        if not _user_can_access_classroom(request.user, classroom):
            return None
        return classroom

    def get(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        if not classroom:
            messages.error(request, 'You are not assigned to this class.')
            return redirect('teacher_dashboard')

        return render(request, 'teacher/create_session.html', {
            'classroom': classroom,
            'default_date': timezone.localdate().isoformat(),
            'default_start': classroom.start_time.strftime('%H:%M') if classroom.start_time else '',
            'default_end': classroom.end_time.strftime('%H:%M') if classroom.end_time else '',
        })

    def post(self, request, class_id):
        classroom = self._get_classroom(request, class_id)
        if not classroom:
            messages.error(request, 'You are not assigned to this class.')
            return redirect('teacher_dashboard')

        from datetime import date as date_cls, time as time_cls
        import datetime

        date_str = request.POST.get('date', '').strip()
        start_str = request.POST.get('start_time', '').strip()
        end_str = request.POST.get('end_time', '').strip()
        go_to_attendance = request.POST.get('go_to_attendance') == 'on'

        # Validate date
        try:
            session_date = datetime.date.fromisoformat(date_str)
        except (ValueError, TypeError):
            messages.error(request, 'Please enter a valid date.')
            return redirect('create_session', class_id=class_id)

        # Validate times
        try:
            start_time = datetime.time.fromisoformat(start_str) if start_str else (classroom.start_time or datetime.time(9, 0))
            end_time = datetime.time.fromisoformat(end_str) if end_str else (classroom.end_time or datetime.time(10, 0))
        except (ValueError, TypeError):
            messages.error(request, 'Please enter valid times.')
            return redirect('create_session', class_id=class_id)

        # Check for duplicate
        if ClassSession.objects.filter(classroom=classroom, date=session_date).exclude(status='cancelled').exists():
            messages.error(request, f'A session already exists for {session_date.strftime("%d %b %Y")}.')
            return redirect('create_session', class_id=class_id)

        session = ClassSession.objects.create(
            classroom=classroom,
            date=session_date,
            start_time=start_time,
            end_time=end_time,
            status='scheduled',
            created_by=request.user,
        )

        log_event(
            user=request.user,
            school=classroom.school,
            category='data_change',
            action='session_created',
            detail={
                'session_id': session.id,
                'classroom_id': classroom.id,
                'classroom': classroom.name,
                'date': str(session_date),
            },
            request=request,
        )

        messages.success(request, f'Session created for {session_date.strftime("%d %b %Y")}.')

        if go_to_attendance:
            return redirect('session_attendance', session_id=session.id)
        return redirect('class_detail', class_id=class_id)


# ---------------------------------------------------------------------------
# 13. CompleteSessionView
# ---------------------------------------------------------------------------

class CompleteSessionView(RoleRequiredMixin, View):
    """Mark a session as completed."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__department', 'classroom__school'),
            id=session_id,
        )

        if not _user_can_access_classroom(request.user, session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('teacher_dashboard')

        if session.status != 'scheduled':
            messages.warning(request, f'Session is already {session.get_status_display().lower()}.')
        else:
            session.status = 'completed'
            session.save(update_fields=['status'])
            log_event(
                user=request.user,
                school=session.classroom.school,
                category='data_change',
                action='session_completed',
                detail={
                    'session_id': session.id,
                    'classroom_id': session.classroom_id,
                    'classroom': session.classroom.name,
                    'date': str(session.date),
                },
                request=request,
            )
            messages.success(request, 'Session marked as completed.')

        return redirect('class_detail', class_id=session.classroom_id)


# ---------------------------------------------------------------------------
# 14. CancelSessionView
# ---------------------------------------------------------------------------

class CancelSessionView(RoleRequiredMixin, View):
    """Cancel a scheduled session."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    ]

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__department', 'classroom__school'),
            id=session_id,
        )

        if not _user_can_access_classroom(request.user, session.classroom):
            messages.error(request, 'You do not have access to this class.')
            return redirect('teacher_dashboard')

        if session.status != 'scheduled':
            messages.warning(request, f'Session is already {session.get_status_display().lower()}.')
        else:
            session.status = 'cancelled'
            reason = request.POST.get('reason', '').strip()
            session.cancellation_reason = reason
            session.save(update_fields=['status', 'cancellation_reason'])
            log_event(
                user=request.user,
                school=session.classroom.school,
                category='data_change',
                action='session_cancelled',
                detail={
                    'session_id': session.id,
                    'classroom_id': session.classroom_id,
                    'classroom': session.classroom.name,
                    'date': str(session.date),
                    'reason': reason,
                },
                request=request,
            )
            messages.success(request, 'Session cancelled.')

        return redirect('class_detail', class_id=session.classroom_id)


# ---------------------------------------------------------------------------
# Parent Link Requests — teacher approval workflow
# ---------------------------------------------------------------------------

def _get_teacher_schools(user):
    """Return queryset of schools where user is an active teacher/admin."""
    return School.objects.filter(
        school_teachers__teacher=user,
        school_teachers__is_active=True,
    )


class ParentLinkRequestsView(RoleRequiredMixin, View):
    """List pending parent link requests for schools where user is a teacher."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
        Role.JUNIOR_TEACHER, Role.ADMIN,
    ]

    def get(self, request):
        schools = _get_teacher_schools(request.user)
        pending_requests = (
            ParentLinkRequest.objects.filter(
                school_student__school__in=schools,
                status=ParentLinkRequest.STATUS_PENDING,
            ).exclude(parent=request.user)  # Teachers cannot approve their own requests
            .select_related(
                'parent', 'school_student', 'school_student__student',
                'school_student__school',
            )
            .order_by('-requested_at')
        )
        return render(request, 'teacher/parent_link_requests.html', {
            'pending_requests': pending_requests,
        })


class ParentLinkApproveView(RoleRequiredMixin, View):
    """Approve a parent link request — creates the ParentStudent link."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
        Role.JUNIOR_TEACHER, Role.ADMIN,
    ]

    def post(self, request, request_id):
        link_request = get_object_or_404(
            ParentLinkRequest, id=request_id, status=ParentLinkRequest.STATUS_PENDING,
        )
        school = link_request.school_student.school

        # Prevent self-approval — a teacher cannot approve their own link request
        if link_request.parent == request.user:
            messages.error(request, 'You cannot approve your own parent link request.')
            return redirect('parent_link_requests')

        # Verify teacher belongs to this school
        if not SchoolTeacher.objects.filter(
            school=school, teacher=request.user, is_active=True,
        ).exists() and not request.user.is_staff:
            messages.error(request, 'You do not have permission to approve this request.')
            return redirect('parent_link_requests')

        # Check max 2 parents per student
        student = link_request.school_student.student
        existing_count = ParentStudent.objects.filter(
            student=student, school=school, is_active=True,
        ).count()
        if existing_count >= 2:
            link_request.status = ParentLinkRequest.STATUS_REJECTED
            link_request.reviewed_at = timezone.now()
            link_request.reviewed_by = request.user
            link_request.rejection_reason = 'Student already has the maximum number of linked parents.'
            link_request.save()
            create_notification(
                user=link_request.parent,
                message=(
                    f'Your request to link to {student.get_full_name() or student.username} '
                    f'at {school.name} could not be approved: student already has 2 linked parents.'
                ),
                notification_type='parent_link_rejected',
                link='/parent/',
            )
            messages.warning(request, 'Student already has the maximum number of parents linked. Request rejected.')
            return redirect('parent_link_requests')

        # Approve: create ParentStudent link
        ParentStudent.objects.get_or_create(
            parent=link_request.parent,
            student=student,
            school=school,
            defaults={
                'relationship': link_request.relationship,
                'is_primary_contact': (existing_count == 0),
                'created_by': request.user,
            },
        )

        link_request.status = ParentLinkRequest.STATUS_APPROVED
        link_request.reviewed_at = timezone.now()
        link_request.reviewed_by = request.user
        link_request.save()

        create_notification(
            user=link_request.parent,
            message=(
                f'Your request to link to {student.get_full_name() or student.username} '
                f'at {school.name} has been approved. You can now view their data.'
            ),
            notification_type='parent_link_approved',
            link='/parent/',
        )

        log_event(
            user=request.user,
            school=school,
            category='data_change',
            action='parent_link_approved',
            detail={
                'request_id': link_request.id,
                'parent': link_request.parent.username,
                'student': student.username,
                'school': school.name,
            },
            request=request,
        )
        messages.success(
            request,
            f'{link_request.parent.get_full_name() or link_request.parent.username} '
            f'has been linked to {student.get_full_name() or student.username}.',
        )
        return redirect('parent_link_requests')


class ParentLinkRejectView(RoleRequiredMixin, View):
    """Reject a parent link request."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
        Role.JUNIOR_TEACHER, Role.ADMIN,
    ]

    def post(self, request, request_id):
        link_request = get_object_or_404(
            ParentLinkRequest, id=request_id, status=ParentLinkRequest.STATUS_PENDING,
        )
        school = link_request.school_student.school

        if not SchoolTeacher.objects.filter(
            school=school, teacher=request.user, is_active=True,
        ).exists() and not request.user.is_staff:
            messages.error(request, 'You do not have permission to reject this request.')
            return redirect('parent_link_requests')

        reason = request.POST.get('rejection_reason', '').strip()
        link_request.status = ParentLinkRequest.STATUS_REJECTED
        link_request.reviewed_at = timezone.now()
        link_request.reviewed_by = request.user
        link_request.rejection_reason = reason
        link_request.save()

        student = link_request.school_student.student
        notification_message = (
            f'Your request to link to {student.get_full_name() or student.username} '
            f'at {school.name} has been declined.'
        )
        if reason:
            notification_message += f' Reason: {reason}'

        create_notification(
            user=link_request.parent,
            message=notification_message,
            notification_type='parent_link_rejected',
            link='/parent/',
        )

        log_event(
            user=request.user,
            school=school,
            category='data_change',
            action='parent_link_rejected',
            detail={
                'request_id': link_request.id,
                'parent': link_request.parent.username,
                'student': student.username,
                'school': school.name,
                'reason': reason,
            },
            request=request,
        )
        messages.success(
            request,
            f'Request from {link_request.parent.get_full_name() or link_request.parent.username} has been rejected.',
        )
        return redirect('parent_link_requests')
