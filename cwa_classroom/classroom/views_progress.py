from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count

from accounts.models import Role
from .views import RoleRequiredMixin
from .models import (
    School, SchoolTeacher, Subject, Level, ClassRoom,
    ProgressCriteria, ProgressRecord, Notification,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_school_or_redirect(request):
    """Return the School for the current session, or None if missing."""
    school_id = request.session.get('current_school_id')
    if not school_id:
        return None
    try:
        return School.objects.get(pk=school_id)
    except School.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Criteria CRUD
# ---------------------------------------------------------------------------

class ProgressCriteriaListView(RoleRequiredMixin, View):
    """List progress criteria for the current school, with optional filters."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER]

    def get(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        criteria = ProgressCriteria.objects.filter(school=school)

        # Optional query-param filters
        subject_id = request.GET.get('subject_id')
        level_id = request.GET.get('level_id')
        if subject_id:
            criteria = criteria.filter(subject_id=subject_id)
        if level_id:
            criteria = criteria.filter(level_id=level_id)

        criteria = criteria.select_related('subject', 'level', 'created_by', 'approved_by')

        subjects = Subject.objects.filter(is_active=True)
        levels = Level.objects.all()

        return render(request, 'progress/criteria_list.html', {
            'school': school,
            'criteria': criteria,
            'subjects': subjects,
            'levels': levels,
            'selected_subject_id': int(subject_id) if subject_id else None,
            'selected_level_id': int(level_id) if level_id else None,
        })


class ProgressCriteriaCreateView(RoleRequiredMixin, View):
    """Create a new ProgressCriteria in draft status."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER]

    def get(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        subjects = Subject.objects.filter(is_active=True)
        levels = Level.objects.all()

        return render(request, 'progress/criteria_form.html', {
            'school': school,
            'subjects': subjects,
            'levels': levels,
        })

    def post(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        subject_id = request.POST.get('subject')
        level_id = request.POST.get('level')
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        order = request.POST.get('order', '0').strip()

        if not name or not subject_id or not level_id:
            messages.error(request, 'Subject, level, and name are required.')
            return render(request, 'progress/criteria_form.html', {
                'school': school,
                'subjects': Subject.objects.filter(is_active=True),
                'levels': Level.objects.all(),
                'form_data': {
                    'subject': subject_id,
                    'level': level_id,
                    'name': name,
                    'description': description,
                    'order': order,
                },
            })

        subject = get_object_or_404(Subject, pk=subject_id)
        level = get_object_or_404(Level, pk=level_id)

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = 0

        ProgressCriteria.objects.create(
            school=school,
            subject=subject,
            level=level,
            name=name,
            description=description,
            order=order_val,
            status='draft',
            created_by=request.user,
        )

        messages.success(request, f'Criteria "{name}" created as draft.')
        return redirect('progress_criteria_list')


# ---------------------------------------------------------------------------
# Submit / Approve / Reject workflow
# ---------------------------------------------------------------------------

class ProgressCriteriaSubmitView(RoleRequiredMixin, View):
    """Submit a draft criteria for senior-teacher approval."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER]

    def post(self, request, criteria_id):
        criteria = get_object_or_404(ProgressCriteria, pk=criteria_id)

        if criteria.status != 'draft':
            messages.error(request, 'Only draft criteria can be submitted for approval.')
            return redirect('progress_criteria_list')

        criteria.status = 'pending_approval'
        criteria.save()

        # Notify all senior teachers at the same school
        senior_memberships = SchoolTeacher.objects.filter(
            school=criteria.school,
            role='senior_teacher',
            is_active=True,
        ).select_related('teacher')

        for membership in senior_memberships:
            Notification.objects.create(
                user=membership.teacher,
                message=(
                    f'{request.user.get_full_name() or request.user.username} '
                    f'submitted criteria "{criteria.name}" '
                    f'({criteria.subject.name} - {criteria.level.display_name}) '
                    f'for approval.'
                ),
                notification_type='criteria_approval',
                link=f'/classroom/progress/criteria/approval/',
            )

        messages.success(request, f'Criteria "{criteria.name}" submitted for approval.')
        return redirect('progress_criteria_list')


class ProgressCriteriaApprovalListView(RoleRequiredMixin, View):
    """List criteria pending approval for the current school."""
    required_roles = [Role.SENIOR_TEACHER]

    def get(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        criteria = (
            ProgressCriteria.objects
            .filter(school=school, status='pending_approval')
            .select_related('subject', 'level', 'created_by')
        )

        return render(request, 'progress/criteria_approval.html', {
            'school': school,
            'criteria': criteria,
        })


class ProgressCriteriaApproveView(RoleRequiredMixin, View):
    """Approve a pending criteria."""
    required_roles = [Role.SENIOR_TEACHER]

    def post(self, request, criteria_id):
        criteria = get_object_or_404(ProgressCriteria, pk=criteria_id)

        if criteria.status != 'pending_approval':
            messages.error(request, 'Only pending criteria can be approved.')
            return redirect('progress_criteria_approval_list')

        criteria.status = 'approved'
        criteria.approved_by = request.user
        criteria.save()

        # Notify the creator
        if criteria.created_by:
            Notification.objects.create(
                user=criteria.created_by,
                message=(
                    f'Your criteria "{criteria.name}" '
                    f'({criteria.subject.name} - {criteria.level.display_name}) '
                    f'has been approved by '
                    f'{request.user.get_full_name() or request.user.username}.'
                ),
                notification_type='criteria_approved',
                link=f'/classroom/progress/criteria/',
            )

        messages.success(request, f'Criteria "{criteria.name}" approved.')
        return redirect('progress_criteria_approval_list')


class ProgressCriteriaRejectView(RoleRequiredMixin, View):
    """Reject a pending criteria."""
    required_roles = [Role.SENIOR_TEACHER]

    def post(self, request, criteria_id):
        criteria = get_object_or_404(ProgressCriteria, pk=criteria_id)

        if criteria.status != 'pending_approval':
            messages.error(request, 'Only pending criteria can be rejected.')
            return redirect('progress_criteria_approval_list')

        criteria.status = 'rejected'
        criteria.save()

        # Notify the creator
        if criteria.created_by:
            Notification.objects.create(
                user=criteria.created_by,
                message=(
                    f'Your criteria "{criteria.name}" '
                    f'({criteria.subject.name} - {criteria.level.display_name}) '
                    f'has been rejected by '
                    f'{request.user.get_full_name() or request.user.username}.'
                ),
                notification_type='criteria_rejected',
                link=f'/classroom/progress/criteria/',
            )

        messages.success(request, f'Criteria "{criteria.name}" rejected.')
        return redirect('progress_criteria_approval_list')


# ---------------------------------------------------------------------------
# Record progress
# ---------------------------------------------------------------------------

class RecordProgressView(RoleRequiredMixin, View):
    """Record (create/update) progress for students in a specific class."""
    required_roles = [Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER]

    def get(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, pk=class_id)

        # Determine approved criteria available for this class
        # Criteria must match the classroom's school, subject, and levels
        criteria_qs = ProgressCriteria.objects.filter(
            school=classroom.school,
            status='approved',
        )
        if classroom.subject:
            criteria_qs = criteria_qs.filter(subject=classroom.subject)
        if classroom.levels.exists():
            criteria_qs = criteria_qs.filter(level__in=classroom.levels.all())

        criteria_qs = criteria_qs.select_related('subject', 'level').order_by(
            'subject__name', 'level__level_number', 'order'
        )

        students = classroom.students.all().order_by('last_name', 'first_name', 'username')

        # Build a lookup of existing records:  {(student_id, criteria_id): record}
        existing_records = ProgressRecord.objects.filter(
            student__in=students,
            criteria__in=criteria_qs,
        ).select_related('criteria', 'student')

        record_map = {}
        for rec in existing_records:
            record_map[(rec.student_id, rec.criteria_id)] = rec

        # Build per-student rows for the template
        student_rows = []
        for student in students:
            row_criteria = []
            for crit in criteria_qs:
                existing = record_map.get((student.id, crit.id))
                row_criteria.append({
                    'criteria': crit,
                    'current_status': existing.status if existing else 'not_started',
                })
            student_rows.append({
                'student': student,
                'criteria_statuses': row_criteria,
            })

        return render(request, 'progress/record_progress.html', {
            'classroom': classroom,
            'criteria': criteria_qs,
            'student_rows': student_rows,
            'status_choices': ProgressRecord.STATUS_CHOICES,
        })

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, pk=class_id)
        students = classroom.students.all()

        criteria_qs = ProgressCriteria.objects.filter(
            school=classroom.school,
            status='approved',
        )
        if classroom.subject:
            criteria_qs = criteria_qs.filter(subject=classroom.subject)
        if classroom.levels.exists():
            criteria_qs = criteria_qs.filter(level__in=classroom.levels.all())

        valid_statuses = {s[0] for s in ProgressRecord.STATUS_CHOICES}
        updated = 0

        for student in students:
            for crit in criteria_qs:
                field_name = f'status_{student.id}_{crit.id}'
                new_status = request.POST.get(field_name, '').strip()

                if new_status not in valid_statuses:
                    continue

                record, created = ProgressRecord.objects.get_or_create(
                    student=student,
                    criteria=crit,
                    defaults={
                        'status': new_status,
                        'recorded_by': request.user,
                    },
                )

                if not created and record.status != new_status:
                    record.status = new_status
                    record.recorded_by = request.user
                    record.save()

                updated += 1

        messages.success(request, f'Progress updated for {updated} record(s).')
        return redirect('record_progress', class_id=class_id)


# ---------------------------------------------------------------------------
# Student progress view
# ---------------------------------------------------------------------------

class StudentProgressView(RoleRequiredMixin, View):
    """Show a student's progress records grouped by subject + level."""
    required_roles = [
        Role.STUDENT,
        Role.INDIVIDUAL_STUDENT,
        Role.SENIOR_TEACHER,
        Role.TEACHER,
        Role.JUNIOR_TEACHER,
    ]

    def get(self, request, student_id):
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, pk=student_id)

        records = (
            ProgressRecord.objects
            .filter(student=student)
            .select_related('criteria__subject', 'criteria__level', 'recorded_by')
            .order_by(
                'criteria__subject__name',
                'criteria__level__level_number',
                'criteria__order',
            )
        )

        # Group records by (subject, level)
        grouped = {}
        for record in records:
            key = (record.criteria.subject, record.criteria.level)
            if key not in grouped:
                grouped[key] = {
                    'subject': record.criteria.subject,
                    'level': record.criteria.level,
                    'records': [],
                }
            grouped[key]['records'].append(record)

        # Convert to a list sorted by subject name then level number
        progress_groups = sorted(
            grouped.values(),
            key=lambda g: (g['subject'].name, g['level'].level_number),
        )

        # Summary counts
        total = records.count()
        achieved = records.filter(status='achieved').count()
        in_progress = records.filter(status='in_progress').count()
        not_started = records.filter(status='not_started').count()

        return render(request, 'progress/student_progress.html', {
            'student': student,
            'progress_groups': progress_groups,
            'total': total,
            'achieved': achieved,
            'in_progress': in_progress,
            'not_started': not_started,
        })
