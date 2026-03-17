from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Max, Q

from accounts.models import Role
from .views import RoleRequiredMixin
from .notifications import create_notification
from .models import (
    School, SchoolTeacher, Subject, Level, ClassRoom, Department,
    ClassStudent, ClassTeacher, DepartmentSubject,
    ProgressCriteria, ProgressRecord, Notification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_school_or_redirect(request):
    """
    Return the School for the current session, or None if missing.

    Falls back to the first active school the user belongs to via
    SchoolTeacher, mirroring the teacher-dashboard helper.
    """
    school_id = request.session.get('current_school_id')
    if school_id:
        try:
            return School.objects.get(pk=school_id)
        except School.DoesNotExist:
            request.session.pop('current_school_id', None)

    # Fallback 1: pick the first school the user is a member of
    membership = (
        SchoolTeacher.objects
        .filter(teacher=request.user, is_active=True)
        .select_related('school')
        .first()
    )
    if membership:
        request.session['current_school_id'] = membership.school_id
        return membership.school

    # Fallback 2: pick the first school the user is admin of
    admin_school = School.objects.filter(admin=request.user, is_active=True).first()
    if admin_school:
        request.session['current_school_id'] = admin_school.id
        return admin_school

    return None


def _build_hierarchical_criteria(criteria_qs):
    """
    Given a queryset / list of ProgressCriteria, return a flat list of dicts
    ``[{'criteria': <obj>, 'is_child': bool}, ...]`` where parents appear
    first and their children follow immediately after, indented.
    """
    all_criteria = list(criteria_qs)
    top_level = [c for c in all_criteria if c.parent_id is None]
    children_map = {}
    for c in all_criteria:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)

    result = []
    for c in top_level:
        result.append({'criteria': c, 'is_child': False})
        for child in children_map.get(c.id, []):
            result.append({'criteria': child, 'is_child': True})
    return result


# ---------------------------------------------------------------------------
# Criteria CRUD
# ---------------------------------------------------------------------------

class ProgressCriteriaListView(RoleRequiredMixin, View):
    """List progress criteria for the current school, with optional filters.
    Also handles inline create/edit via POST actions."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
    ]

    def _build_subject_levels_json(self, school):
        """Build a JSON mapping of subject_id -> [{id, name}] for levels, excluding Basic Facts."""
        import json
        levels = Level.objects.filter(
            Q(school__isnull=True) | Q(school=school),
            subject__isnull=False,
        ).exclude(
            level_number__gte=100, level_number__lt=200,
        ).select_related('subject').order_by('subject__name', 'level_number')

        mapping = {}
        for lv in levels:
            subj_id = str(lv.subject_id)
            if subj_id not in mapping:
                mapping[subj_id] = []
            mapping[subj_id].append({'id': lv.id, 'name': lv.display_name})
        return json.dumps(mapping)

    def _get_context(self, request, school, extra=None):
        criteria = ProgressCriteria.objects.filter(school=school)

        subject_id = request.GET.get('subject_id')
        level_id = request.GET.get('level_id')
        if subject_id:
            criteria = criteria.filter(subject_id=subject_id)
        if level_id:
            criteria = criteria.filter(level_id=level_id)

        criteria = criteria.select_related(
            'subject', 'level', 'created_by', 'approved_by', 'parent',
        ).order_by('subject__name', 'level__level_number', 'order', 'name')

        ctx = {
            'school': school,
            'hierarchical_criteria': _build_hierarchical_criteria(criteria),
            'subjects': Subject.objects.filter(is_active=True).order_by('name'),
            'subject_levels_json': self._build_subject_levels_json(school),
            'selected_subject_id': int(subject_id) if subject_id else None,
            'selected_level_id': int(level_id) if level_id else None,
        }
        if extra:
            ctx.update(extra)
        return ctx

    def get(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        # If editing, load the criteria to edit
        edit_id = request.GET.get('edit')
        edit_criteria = None
        if edit_id:
            edit_criteria = ProgressCriteria.objects.filter(
                pk=edit_id, school=school,
            ).select_related('subject', 'level').first()

        return render(request, 'progress/criteria_list.html',
                      self._get_context(request, school, {'edit_criteria': edit_criteria}))

    def post(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        action = request.POST.get('action', 'create')

        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        order = request.POST.get('order', '0').strip()
        subject_id = request.POST.get('subject')
        level_id = request.POST.get('level')  # empty = All Levels
        parent_id = request.POST.get('parent')

        if not name or not subject_id:
            messages.error(request, 'Subject and name are required.')
            return redirect('progress_criteria_list')

        subject = get_object_or_404(Subject, pk=subject_id)
        level = get_object_or_404(Level, pk=level_id) if level_id else None

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = 0

        auto_approve = (
            request.user.has_role(Role.SENIOR_TEACHER)
            or request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            or request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
        )

        if action == 'edit':
            criteria_id = request.POST.get('criteria_id')
            criteria = get_object_or_404(ProgressCriteria, pk=criteria_id, school=school)
            criteria.name = name
            criteria.subject = subject
            criteria.level = level
            criteria.description = description
            criteria.order = order_val
            if parent_id:
                criteria.parent_id = parent_id
            criteria.save()
            messages.success(request, f'Criteria "{name}" updated.')
        else:
            parent = None
            if parent_id:
                parent = ProgressCriteria.objects.filter(pk=parent_id, school=school).first()
            ProgressCriteria.objects.create(
                school=school,
                subject=subject,
                level=level,
                parent=parent,
                name=name,
                description=description,
                order=order_val,
                status='approved' if auto_approve else 'draft',
                created_by=request.user,
                approved_by=request.user if auto_approve else None,
            )
            if auto_approve:
                messages.success(request, f'Criteria "{name}" created and approved.')
            else:
                messages.success(request, f'Criteria "{name}" created as draft.')

        return redirect('progress_criteria_list')


class ProgressCriteriaCreateView(RoleRequiredMixin, View):
    """Create a new ProgressCriteria in draft status."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
    ]

    def _build_subject_levels_json(self, school):
        """Build a JSON mapping of subject_id -> [{id, name}] for levels, excluding Basic Facts."""
        import json
        levels = Level.objects.filter(
            Q(school__isnull=True) | Q(school=school),
            subject__isnull=False,
        ).exclude(
            level_number__gte=100, level_number__lt=200,  # Exclude Basic Facts (100-199)
        ).select_related('subject').order_by('subject__name', 'level_number')

        mapping = {}
        for lv in levels:
            subj_id = str(lv.subject_id)
            if subj_id not in mapping:
                mapping[subj_id] = []
            mapping[subj_id].append({'id': lv.id, 'name': lv.display_name})
        return json.dumps(mapping)

    def get(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        # Support creating sub-criteria via ?parent=<id>
        parent_id = request.GET.get('parent')
        parent_criteria = None
        if parent_id:
            parent_criteria = ProgressCriteria.objects.filter(
                pk=parent_id, school=school,
            ).select_related('subject', 'level').first()

        subjects = Subject.objects.filter(is_active=True).order_by('name')

        return render(request, 'progress/criteria_form.html', {
            'school': school,
            'subjects': subjects,
            'subject_levels_json': self._build_subject_levels_json(school),
            'parent_criteria': parent_criteria,
        })

    def post(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        # Check for parent criteria
        parent_id = request.POST.get('parent')
        parent_criteria = None
        if parent_id:
            parent_criteria = ProgressCriteria.objects.filter(
                pk=parent_id, school=school,
            ).select_related('subject', 'level').first()

        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        order = request.POST.get('order', '0').strip()

        # Helper to re-render the form on validation error
        def _rerender(error_msg, form_data):
            messages.error(request, error_msg)
            return render(request, 'progress/criteria_form.html', {
                'school': school,
                'subjects': Subject.objects.filter(is_active=True).order_by('name'),
                'subject_levels_json': self._build_subject_levels_json(school),
                'parent_criteria': parent_criteria,
                'form_data': form_data,
            })

        # Inherit subject/level from parent if set, otherwise read from form
        if parent_criteria:
            subject = parent_criteria.subject
            level = parent_criteria.level
        else:
            subject_id = request.POST.get('subject')
            level_id = request.POST.get('level')  # empty string = "All Levels"
            if not name or not subject_id:
                return _rerender('Subject and name are required.', {
                    'subject': subject_id,
                    'level': level_id,
                    'name': name,
                    'description': description,
                    'order': order,
                })
            subject = get_object_or_404(Subject, pk=subject_id)
            level = get_object_or_404(Level, pk=level_id) if level_id else None

        if not name:
            return _rerender('Name is required.', {
                'name': name,
                'description': description,
                'order': order,
            })

        try:
            order_val = int(order)
        except (ValueError, TypeError):
            order_val = 0

        # Senior Teachers, HoD, and HoI get auto-approved criteria
        auto_approve = (
            request.user.has_role(Role.SENIOR_TEACHER)
            or request.user.has_role(Role.HEAD_OF_DEPARTMENT)
            or request.user.has_role(Role.HEAD_OF_INSTITUTE)
            or request.user.has_role(Role.INSTITUTE_OWNER)
        )

        criteria = ProgressCriteria.objects.create(
            school=school,
            subject=subject,
            level=level,
            parent=parent_criteria,
            name=name,
            description=description,
            order=order_val,
            status='approved' if auto_approve else 'draft',
            created_by=request.user,
            approved_by=request.user if auto_approve else None,
        )

        if auto_approve:
            messages.success(request, f'Criteria "{name}" created and approved.')
        else:
            messages.success(request, f'Criteria "{name}" created as draft.')
        return redirect('progress_criteria_list')


# ---------------------------------------------------------------------------
# Submit / Approve / Reject workflow
# ---------------------------------------------------------------------------

class ProgressCriteriaSubmitView(RoleRequiredMixin, View):
    """Submit a draft criteria for senior-teacher approval."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
    ]

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
            create_notification(
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
    required_roles = [
        Role.SENIOR_TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def get(self, request):
        school = _get_school_or_redirect(request)
        if school is None:
            messages.error(request, 'No school selected. Please select a school first.')
            return redirect('subjects_hub')

        criteria = (
            ProgressCriteria.objects
            .filter(school=school, status='pending_approval')
            .select_related('subject', 'level', 'created_by', 'parent')
        )

        return render(request, 'progress/criteria_approval.html', {
            'school': school,
            'criteria': criteria,
        })


class ProgressCriteriaApproveView(RoleRequiredMixin, View):
    """Approve a pending criteria."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

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
            create_notification(
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
    required_roles = [
        Role.SENIOR_TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def post(self, request, criteria_id):
        criteria = get_object_or_404(ProgressCriteria, pk=criteria_id)

        if criteria.status != 'pending_approval':
            messages.error(request, 'Only pending criteria can be rejected.')
            return redirect('progress_criteria_approval_list')

        criteria.status = 'rejected'
        criteria.save()

        # Notify the creator
        if criteria.created_by:
            create_notification(
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
# Record progress (standalone page)
# ---------------------------------------------------------------------------

class RecordProgressView(RoleRequiredMixin, View):
    """Record (create/update) progress for students in a specific class."""
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
    ]

    def get(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, pk=class_id)

        # Determine approved criteria available for this class
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

        hierarchical_criteria = _build_hierarchical_criteria(criteria_qs)

        students = classroom.students.all().order_by('last_name', 'first_name', 'username')

        # Build a lookup of *latest* records: {(student_id, criteria_id): status}
        # Since there can be multiple records per (student, criteria) across sessions,
        # pick the one with the highest id (most recent).
        latest_ids_qs = (
            ProgressRecord.objects
            .filter(student__in=students, criteria__in=criteria_qs)
            .values('student_id', 'criteria_id')
            .annotate(latest_id=Max('id'))
        )
        latest_ids = [r['latest_id'] for r in latest_ids_qs]
        existing_records = ProgressRecord.objects.filter(id__in=latest_ids)

        record_map = {}
        for rec in existing_records:
            record_map[(rec.student_id, rec.criteria_id)] = rec

        # Build per-student rows for the template
        student_rows = []
        for student in students:
            row_criteria = []
            for h_item in hierarchical_criteria:
                crit = h_item['criteria']
                existing = record_map.get((student.id, crit.id))
                row_criteria.append({
                    'criteria': crit,
                    'is_child': h_item['is_child'],
                    'current_status': existing.status if existing else 'not_started',
                })
            student_rows.append({
                'student': student,
                'criteria_statuses': row_criteria,
            })

        return render(request, 'progress/record_progress.html', {
            'classroom': classroom,
            'hierarchical_criteria': hierarchical_criteria,
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
            criteria_qs = criteria_qs.filter(
                Q(level__in=classroom.levels.all()) | Q(level__isnull=True)
            )

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
                    session=None,
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
        Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE,
    ]

    def get(self, request, student_id):
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, pk=student_id)

        # Get latest record per (student, criteria) using Max(id)
        latest_ids_qs = (
            ProgressRecord.objects
            .filter(student=student)
            .values('criteria_id')
            .annotate(latest_id=Max('id'))
        )
        latest_ids = [r['latest_id'] for r in latest_ids_qs]

        records = (
            ProgressRecord.objects
            .filter(id__in=latest_ids)
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
        total = len(latest_ids)
        achieved = sum(1 for r in records if r.status == 'achieved')
        in_progress_count = sum(1 for r in records if r.status == 'in_progress')
        not_started = sum(1 for r in records if r.status == 'not_started')

        return render(request, 'progress/student_progress.html', {
            'student': student,
            'progress_groups': progress_groups,
            'total': total,
            'achieved': achieved,
            'in_progress': in_progress_count,
            'not_started': not_started,
        })


# ---------------------------------------------------------------------------
# Student Progress Report (overview across all students)
# ---------------------------------------------------------------------------

class StudentProgressReportView(RoleRequiredMixin, View):
    """Show a filterable list of students with their progress summary.

    Role-based access:
    - HoI/Institute Owner: all students in all schools they own
    - HoD: students in their department classes + classes they teach
    - Teachers: students in classes they teach
    """
    required_roles = [
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER,
    ]

    def _get_accessible_classes(self, user):
        """Return ClassRoom queryset the user can see based on role."""
        is_hoi = user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER)
        is_hod = user.has_role(Role.HEAD_OF_DEPARTMENT)

        if is_hoi:
            school_ids = School.objects.filter(admin=user).values_list('id', flat=True)
            return ClassRoom.objects.filter(school_id__in=school_ids, is_active=True)

        if is_hod:
            # Classes in departments they head + classes they teach
            dept_ids = Department.objects.filter(head=user, is_active=True).values_list('id', flat=True)
            dept_class_ids = ClassRoom.objects.filter(department_id__in=dept_ids, is_active=True).values_list('id', flat=True)
            teach_class_ids = ClassTeacher.objects.filter(teacher=user).values_list('classroom_id', flat=True)
            combined_ids = set(dept_class_ids) | set(teach_class_ids)
            return ClassRoom.objects.filter(id__in=combined_ids, is_active=True)

        # Teachers: only classes they teach
        teach_class_ids = ClassTeacher.objects.filter(teacher=user).values_list('classroom_id', flat=True)
        return ClassRoom.objects.filter(id__in=teach_class_ids, is_active=True)

    def get(self, request):
        accessible_classes = self._get_accessible_classes(request.user)

        # Build filter options
        dept_ids = accessible_classes.values_list('department_id', flat=True).distinct()
        departments = Department.objects.filter(id__in=dept_ids, is_active=True).order_by('name')

        subject_ids = accessible_classes.exclude(level__subject__isnull=True).values_list('level__subject_id', flat=True).distinct()
        subjects = Subject.objects.filter(id__in=subject_ids, is_active=True).order_by('name')

        classes = accessible_classes.select_related('department', 'level__subject').order_by('name')

        # Apply filters
        filter_dept = request.GET.get('department')
        filter_subject = request.GET.get('subject')
        filter_class = request.GET.get('classroom')

        filtered_classes = accessible_classes
        if filter_dept:
            filtered_classes = filtered_classes.filter(department_id=filter_dept)
        if filter_subject:
            filtered_classes = filtered_classes.filter(level__subject_id=filter_subject)
        if filter_class:
            filtered_classes = filtered_classes.filter(id=filter_class)

        # Get students in filtered classes
        student_ids = ClassStudent.objects.filter(
            classroom__in=filtered_classes
        ).values_list('student_id', flat=True).distinct()

        from accounts.models import CustomUser
        students_qs = CustomUser.objects.filter(id__in=student_ids).order_by('first_name', 'last_name')

        # Build progress summary per student
        student_data = []
        for student in students_qs:
            # Get latest record per criteria
            latest_ids_qs = (
                ProgressRecord.objects
                .filter(student=student)
                .values('criteria_id')
                .annotate(latest_id=Max('id'))
            )
            latest_ids = [r['latest_id'] for r in latest_ids_qs]
            records = ProgressRecord.objects.filter(id__in=latest_ids)
            total = len(latest_ids)
            achieved = sum(1 for r in records if r.status == 'achieved')
            in_progress_count = sum(1 for r in records if r.status == 'in_progress')
            not_started = sum(1 for r in records if r.status == 'not_started')

            # Get student's classes and department
            student_classes = ClassRoom.objects.filter(
                class_students__student=student,
                id__in=filtered_classes
            ).select_related('department').order_by('name')

            student_data.append({
                'student': student,
                'classes': student_classes,
                'department': student_classes.first().department if student_classes.exists() else None,
                'total': total,
                'achieved': achieved,
                'in_progress': in_progress_count,
                'not_started': not_started,
            })

        return render(request, 'progress/student_progress_report.html', {
            'student_data': student_data,
            'departments': departments,
            'subjects': subjects,
            'classes': classes,
            'filter_dept': filter_dept or '',
            'filter_subject': filter_subject or '',
            'filter_class': filter_class or '',
        })
