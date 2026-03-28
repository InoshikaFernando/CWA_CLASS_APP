"""
attendance/views_student.py
============================
Moved from classroom/views_student.py as part of CPP-64.
Contains student-facing attendance views only.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from classroom.models import ClassRoom, ClassStudent
from audit.services import log_event
from .models import AbsenceToken, ClassSession, StudentAttendance



class StudentAttendanceHistoryView(LoginRequiredMixin, View):
    """Show the student's own attendance records across all enrolled classes."""

    def get(self, request):
        # Get all classes the student belongs to
        enrolled_class_ids = ClassStudent.objects.filter(
            student=request.user
        ).values_list('classroom_id', flat=True)

        # Fetch all attendance records for this student across enrolled classes
        # Include both enrolled class attendance AND makeup attendance (different classes)
        attendance_records = (
            StudentAttendance.objects.filter(
                Q(session__classroom_id__in=enrolled_class_ids) | Q(makeup_token__isnull=False),
                student=request.user,
            )
            .select_related('session', 'session__classroom', 'makeup_token')
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
            ClassSession.objects.select_related('classroom', 'classroom__school'),
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

        log_event(
            user=request.user, school=session.classroom.school,
            category='data_change', action='student_attendance_submitted',
            detail={'session_id': session.id, 'classroom': session.classroom.name,
                    'status': status},
            request=request,
        )

        messages.success(
            request,
            'Your attendance has been submitted and is pending teacher approval.'
        )
        return redirect('student_class_detail', class_id=session.classroom_id)


# ---------------------------------------------------------------------------
# Absence Token Views
# ---------------------------------------------------------------------------


class RequestAbsenceTokenView(LoginRequiredMixin, View):
    """Student/parent requests an absence token for a class (optionally for a specific session)."""

    def post(self, request):
        classroom_id = request.POST.get('classroom_id')
        session_id = request.POST.get('session_id', '').strip()
        note = request.POST.get('note', '').strip()

        classroom = get_object_or_404(ClassRoom, id=classroom_id)

        # Verify student is enrolled
        if not ClassStudent.objects.filter(
            classroom=classroom, student=request.user, is_active=True,
        ).exists():
            messages.error(request, 'You are not enrolled in this class.')
            return redirect('student_my_classes')

        # Resolve optional session
        session = None
        if session_id:
            session = ClassSession.objects.filter(
                id=session_id, classroom=classroom,
            ).first()

        # Prevent duplicate token for the same session
        if session and AbsenceToken.objects.filter(
            student=request.user, original_session=session,
        ).exists():
            messages.info(request, 'You already have an absence token for this session.')
            return redirect('student_class_detail', class_id=classroom.id)

        token = AbsenceToken.objects.create(
            student=request.user,
            original_session=session,
            original_classroom=classroom,
            created_by=request.user,
            note=note,
        )

        # Also mark as absent for the specific session if provided
        if session:
            StudentAttendance.objects.update_or_create(
                session=session,
                student=request.user,
                defaults={
                    'status': 'absent',
                    'marked_by': request.user,
                    'self_reported': True,
                },
            )

        log_event(
            user=request.user, school=classroom.school,
            category='data_change', action='absence_token_requested',
            detail={
                'token_id': token.id,
                'classroom': classroom.name,
                'session_id': session.id if session else None,
                'note': note,
            },
            request=request,
        )

        messages.success(request, 'Absence token issued. You can use it to attend a makeup class at the same level.')
        return redirect('student_absence_tokens')


class MyAbsenceTokensView(LoginRequiredMixin, View):
    """List all absence tokens for the current student."""

    def get(self, request):
        tokens = (
            AbsenceToken.objects.filter(student=request.user)
            .select_related(
                'original_classroom', 'original_classroom__subject',
                'original_session', 'redeemed_session',
                'redeemed_session__classroom',
            )
            .order_by('-created_at')
        )

        available_tokens = [t for t in tokens if not t.redeemed]
        used_tokens = [t for t in tokens if t.redeemed]

        return render(request, 'student/absence_tokens.html', {
            'available_tokens': available_tokens,
            'used_tokens': used_tokens,
        })


class AvailableMakeupSessionsView(LoginRequiredMixin, View):
    """Show sessions from other classes at the same level that a token can be redeemed for."""

    def get(self, request, token_id):
        token = get_object_or_404(
            AbsenceToken.objects.select_related('original_classroom', 'original_classroom__school'),
            id=token_id,
            student=request.user,
            redeemed=False,
        )

        original_class = token.original_classroom
        # Find levels covered by the original class
        level_ids = list(original_class.levels.values_list('id', flat=True))

        if not level_ids:
            messages.warning(request, 'No levels assigned to the original class. Cannot find makeup sessions.')
            return redirect('student_absence_tokens')

        # Find other classes in the same school covering at least one of these levels
        sibling_classes = (
            ClassRoom.objects.filter(
                school=original_class.school,
                levels__id__in=level_ids,
                is_active=True,
            )
            .exclude(id=original_class.id)
            .distinct()
        )

        # Find scheduled or completed sessions from those classes
        sessions = (
            ClassSession.objects.filter(
                classroom__in=sibling_classes,
                status__in=['scheduled', 'completed'],
            )
            .select_related('classroom', 'classroom__subject')
            .order_by('date', 'start_time')
        )

        # Exclude sessions where the student already has attendance
        attended_session_ids = StudentAttendance.objects.filter(
            student=request.user,
            session__in=sessions,
        ).values_list('session_id', flat=True)
        sessions = sessions.exclude(id__in=attended_session_ids)

        return render(request, 'student/available_makeup_sessions.html', {
            'token': token,
            'sessions': sessions,
        })


class RedeemAbsenceTokenView(LoginRequiredMixin, View):
    """Redeem an absence token to attend a makeup session."""

    def post(self, request, token_id):
        token = get_object_or_404(
            AbsenceToken.objects.select_related('original_classroom'),
            id=token_id,
            student=request.user,
            redeemed=False,
        )

        session_id = request.POST.get('session_id')
        session = get_object_or_404(
            ClassSession.objects.select_related('classroom', 'classroom__school'),
            id=session_id,
        )

        # Validate: session's class must share a level with the original class
        original_level_ids = set(
            token.original_classroom.levels.values_list('id', flat=True)
        )
        session_level_ids = set(
            session.classroom.levels.values_list('id', flat=True)
        )
        if not original_level_ids & session_level_ids:
            messages.error(request, 'This session does not cover the same level as your original class.')
            return redirect('student_available_makeup_sessions', token_id=token.id)

        # Validate: same school
        if session.classroom.school_id != token.original_classroom.school_id:
            messages.error(request, 'Makeup sessions must be within the same school.')
            return redirect('student_available_makeup_sessions', token_id=token.id)

        # Check no existing attendance for this student in this session
        if StudentAttendance.objects.filter(session=session, student=request.user).exists():
            messages.error(request, 'You already have an attendance record for this session.')
            return redirect('student_available_makeup_sessions', token_id=token.id)

        # Create makeup attendance
        StudentAttendance.objects.create(
            session=session,
            student=request.user,
            status='present',
            marked_by=request.user,
            self_reported=True,
            makeup_token=token,
        )

        # Mark token as redeemed
        token.redeemed = True
        token.redeemed_session = session
        token.redeemed_at = timezone.now()
        token.save(update_fields=['redeemed', 'redeemed_session', 'redeemed_at'])

        log_event(
            user=request.user, school=session.classroom.school,
            category='data_change', action='absence_token_redeemed',
            detail={
                'token_id': token.id,
                'original_classroom': token.original_classroom.name,
                'makeup_session_id': session.id,
                'makeup_classroom': session.classroom.name,
            },
            request=request,
        )

        messages.success(
            request,
            f'Token redeemed! You are marked as attending {session.classroom.name} on {session.date.strftime("%d %b %Y")}. Pending teacher approval.'
        )
        return redirect('student_absence_tokens')


# ---------------------------------------------------------------------------
# 6. EnrollGlobalClassView
# ---------------------------------------------------------------------------