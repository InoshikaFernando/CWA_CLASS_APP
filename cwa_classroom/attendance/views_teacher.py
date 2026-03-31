"""
attendance/views_teacher.py
============================
Moved from classroom/views_teacher.py as part of CPP-64.
Contains all teacher-facing attendance and session lifecycle views.
"""

from datetime import timedelta
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from accounts.models import Role
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher,
    Department, Enrollment,
    ProgressCriteria, ProgressRecord,
    School, SchoolStudent, SchoolTeacher,
)
from classroom.views import RoleRequiredMixin
from classroom.notifications import create_notification
from classroom.views_progress import _build_hierarchical_criteria
from audit.services import log_event
from .models import ClassSession, StudentAttendance, TeacherAttendance


def _get_teacher_current_school(request):
    from classroom.views_teacher import _get_teacher_current_school as _orig
    return _orig(request)


def _get_teacher_classes(user, school):
    from classroom.views_teacher import _get_teacher_classes as _orig
    return _orig(user, school)



class SessionAttendanceView(RoleRequiredMixin, View):
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
                'is_makeup': False,
            })

        # Include makeup students (not enrolled but attending via absence token)
        makeup_records = StudentAttendance.objects.filter(
            session=session, makeup_token__isnull=False,
        ).select_related('student', 'makeup_token', 'makeup_token__original_classroom')
        enrolled_ids = set(active_ids)
        for sa in makeup_records:
            if sa.student_id not in enrolled_ids:
                students_with_status.append({
                    'student': sa.student,
                    'current_status': sa.status,
                    'self_reported': sa.self_reported,
                    'approved': sa.approved_by is not None,
                    'is_makeup': True,
                    'makeup_from': sa.makeup_token.original_classroom.name,
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

        # ----- Save attendance for makeup students -----
        makeup_records = StudentAttendance.objects.filter(
            session=session, makeup_token__isnull=False,
        ).select_related('student')
        enrolled_id_set = set(active_ids)
        for sa in makeup_records:
            if sa.student_id in enrolled_id_set:
                continue  # already handled above
            status = request.POST.get(f'status_{sa.student_id}', '').strip()
            if status not in ('present', 'absent', 'late'):
                continue
            sa.status = status
            sa.marked_by = request.user
            sa.self_reported = False
            sa.approved_by = None
            sa.approved_at = None
            sa.save(update_fields=['status', 'marked_by', 'self_reported', 'approved_by', 'approved_at'])
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
            log_event(
                user=request.user, school=session.classroom.school,
                category='data_change', action='attendance_marked',
                detail={'session_id': session.id, 'classroom': session.classroom.name,
                        'students_saved': saved_count, 'progress_saved': progress_saved,
                        'session_completed': True},
                request=request,
            )
            return redirect('class_detail', class_id=session.classroom_id)

        msg = f'Attendance saved for {saved_count} student(s).'
        if progress_saved:
            msg += f' Progress saved for {progress_saved} record(s).'
        messages.success(request, msg)
        log_event(
            user=request.user, school=session.classroom.school,
            category='data_change', action='attendance_marked',
            detail={'session_id': session.id, 'classroom': session.classroom.name,
                    'students_saved': saved_count, 'progress_saved': progress_saved,
                    'session_completed': False},
            request=request,
        )
        return redirect('session_attendance', session_id=session_id)


# ---------------------------------------------------------------------------
# 7. TeacherSelfAttendanceView
# ---------------------------------------------------------------------------

class TeacherSelfAttendanceView(RoleRequiredMixin, View):
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def post(self, request, session_id):
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__school'),
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
            user=request.user, school=session.classroom.school,
            category='data_change', action='teacher_self_attendance_recorded',
            detail={'session_id': session.id, 'classroom': session.classroom.name,
                    'status': status},
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

class StudentAttendanceApprovalListView(RoleRequiredMixin, View):
    """List self-reported student attendance records pending teacher approval."""
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


class StudentAttendanceApproveView(RoleRequiredMixin, View):
    """Approve a single self-reported student attendance record."""
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
            user=request.user, school=record.session.classroom.school,
            category='data_change', action='student_attendance_approved',
            detail={'attendance_id': record.id, 'student': record.student.username,
                    'session_id': record.session_id,
                    'classroom': record.session.classroom.name},
            request=request,
        )

        messages.success(
            request,
            f'Approved attendance for {record.student.get_full_name() or record.student.username}.'
        )
        return redirect('attendance_approvals')


class StudentAttendanceRejectView(RoleRequiredMixin, View):
    """Reject (delete) a self-reported student attendance record so they can re-mark."""
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
        school = record.session.classroom.school
        detail = {'attendance_id': record.id, 'student': record.student.username,
                  'session_id': record.session_id,
                  'classroom': record.session.classroom.name}
        record.delete()

        log_event(
            user=request.user, school=school,
            category='data_change', action='student_attendance_rejected',
            detail=detail,
            request=request,
        )

        messages.success(request, f'Rejected attendance for {student_name}.')
        return redirect('attendance_approvals')


class StudentAttendanceBulkApproveView(RoleRequiredMixin, View):
    """Bulk approve all pending self-reported records for a session."""
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
            user=request.user, school=session.classroom.school,
            category='data_change', action='student_attendance_bulk_approved',
            detail={'session_id': session.id, 'classroom': session.classroom.name,
                    'approved_count': count},
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
            user=request.user, school=classroom.school,
            category='data_change', action='attendance_session_created',
            detail={'session_id': session.id, 'classroom': classroom.name,
                    'date': str(today), 'method': 'quick_start'},
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
        school = session.classroom.school
        session_label = f'{session.date.strftime("%d %b %Y")} ({session.start_time.strftime("%H:%M")}\u2013{session.end_time.strftime("%H:%M")})'
        session_detail = {'session_id': session.id, 'classroom': session.classroom.name,
                          'date': str(session.date), 'session_label': session_label}

        # Delete related records explicitly, then the session itself
        StudentAttendance.objects.filter(session=session).delete()
        TeacherAttendance.objects.filter(session=session).delete()
        ProgressRecord.objects.filter(session=session).delete()
        session.delete()

        log_event(
            user=request.user, school=school,
            category='data_change', action='attendance_session_deleted',
            detail=session_detail,
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
            user=request.user, school=classroom.school,
            category='data_change', action='attendance_session_created',
            detail={'session_id': session.id, 'classroom': classroom.name,
                    'date': str(session_date), 'method': 'manual_create'},
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
                user=request.user, school=session.classroom.school,
                category='data_change', action='session_completed',
                detail={'session_id': session.id, 'classroom': session.classroom.name,
                        'date': str(session.date)},
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
            session.cancellation_reason = request.POST.get('reason', '').strip()
            session.save(update_fields=['status', 'cancellation_reason'])
            log_event(
                user=request.user, school=session.classroom.school,
                category='data_change', action='session_cancelled',
                detail={'session_id': session.id, 'classroom': session.classroom.name,
                        'date': str(session.date),
                        'reason': session.cancellation_reason},
                request=request,
            )
            messages.success(request, 'Session cancelled.')

        return redirect('class_detail', class_id=session.classroom_id)
