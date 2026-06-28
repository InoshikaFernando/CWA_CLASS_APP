from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Max, Q

from accounts.models import Role
from audit.services import log_event
from billing.mixins import ModuleRequiredMixin
from billing.models import ModuleSubscription
from .views import RoleRequiredMixin
from .notifications import create_notification
from .progress_summary import build_summary
from .models import (
    School, SchoolTeacher, Subject, Level, ClassRoom, Department,
    ClassStudent, ClassTeacher, DepartmentSubject, Term, ParentStudent,
    ProgressCriteria, ProgressRecord, Notification,
    ProgressReportComment, ProgressReport,
)


# Roles allowed to author/edit progress report comments and send reports.
TEACHER_ROLES = [
    Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
    Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
    Role.INSTITUTE_OWNER,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _criteria_scope_label(criteria):
    """Human label for a criterion's scope, e.g. 'Mathematics - Year 5'.

    A null subject renders as 'All Subjects' and a null level as 'All Levels'
    (see §12.6), so this is safe for subject-agnostic / all-level criteria.
    """
    subject = criteria.subject.name if criteria.subject else 'All Subjects'
    level = criteria.level.display_name if criteria.level else 'All Levels'
    return f'{subject} - {level}'


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


def _is_teacher(user):
    """True if the user holds any staff/teacher role (or is a superuser)."""
    return user.is_superuser or any(user.has_role(r) for r in TEACHER_ROLES)


def _school_for_student(request, student):
    """Resolve the most relevant School for a student-progress context.

    Staff use their currently-selected school; students/parents fall back to
    the student's own active enrolment.
    """
    if _is_teacher(request.user):
        school = _get_school_or_redirect(request)
        if school is not None:
            return school
    enrolment = (
        ClassStudent.objects
        .filter(student=student, is_active=True)
        .select_related('classroom__school')
        .first()
    )
    return enrolment.classroom.school if enrolment else None


def _build_student_progress(student):
    """Build a student's progress grouped by (subject, level) plus overall counts.

    Returns ``(grouped_progress, overall)`` where ``grouped_progress`` is a
    sorted list of group dicts and ``overall`` is a summary-counts dict. Shared
    by the on-screen progress view and the generated report.
    """
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

    # 'achieved' = proficient bucket (Confident + Advanced); 'in_progress' =
    # developing bucket (Beginning + Developing). See §12.7.
    _PROFICIENT = ProgressRecord.PROFICIENT_STATUSES
    _DEVELOPING = ProgressRecord.DEVELOPING_STATUSES

    for group_data in grouped.values():
        recs = group_data['records']
        group_data['total'] = len(recs)
        group_data['achieved'] = sum(1 for r in recs if r.status in _PROFICIENT)

    grouped_progress = sorted(
        grouped.values(),
        # All-Subjects (subject=None) and All-Levels (level=None) sort first.
        key=lambda g: (
            g['subject'].name if g['subject'] else '',
            g['level'].level_number if g['level'] else -1,
        ),
    )

    overall = {
        'total': len(latest_ids),
        'achieved': sum(1 for r in records if r.status in _PROFICIENT),
        'in_progress': sum(1 for r in records if r.status in _DEVELOPING),
        'not_started': sum(1 for r in records if r.status == 'not_started'),
    }
    return grouped_progress, overall


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

class ProgressCriteriaListView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """List progress criteria for the current school, with optional filters.
    Also handles inline create/edit via POST actions."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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

        if not name:
            messages.error(request, 'Name is required.')
            return redirect('progress_criteria_list')

        # subject_id empty / 'all' → All Subjects (subject=None). See §12.6.
        subject = None
        if subject_id and subject_id != 'all':
            subject = get_object_or_404(Subject, pk=subject_id)
        # A level is meaningless without a subject (levels are subject-scoped).
        level = get_object_or_404(Level, pk=level_id) if (level_id and subject) else None

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
            log_event(
                user=request.user, school=school, category='data_change',
                action='progress_criteria_edited',
                detail={'criteria_id': criteria.id, 'name': name, 'subject': subject.name if subject else 'All Subjects',
                        'level': level.display_name if level else None},
                request=request,
            )
            messages.success(request, f'Criteria "{name}" updated.')
        else:
            parent = None
            if parent_id:
                parent = ProgressCriteria.objects.filter(pk=parent_id, school=school).first()
            new_criteria = ProgressCriteria.objects.create(
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
            log_event(
                user=request.user, school=school, category='data_change',
                action='progress_criteria_created',
                detail={'criteria_id': new_criteria.id, 'name': name, 'subject': subject.name if subject else 'All Subjects',
                        'level': level.display_name if level else None,
                        'auto_approved': auto_approve},
                request=request,
            )
            if auto_approve:
                messages.success(request, f'Criteria "{name}" created and approved.')
            else:
                messages.success(request, f'Criteria "{name}" created as draft.')

        return redirect('progress_criteria_list')


class ProgressCriteriaCreateView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Create a new ProgressCriteria in draft status."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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
            if not name:
                return _rerender('Name is required.', {
                    'subject': subject_id,
                    'level': level_id,
                    'name': name,
                    'description': description,
                    'order': order,
                })
            # subject_id empty / 'all' → All Subjects (subject=None). See §12.6.
            subject = None
            if subject_id and subject_id != 'all':
                subject = get_object_or_404(Subject, pk=subject_id)
            # A level is meaningless without a subject (levels are subject-scoped).
            level = get_object_or_404(Level, pk=level_id) if (level_id and subject) else None

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

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_criteria_created',
            detail={'criteria_id': criteria.id, 'name': name, 'subject': subject.name if subject else 'All Subjects',
                    'level': level.display_name if level else None,
                    'parent_id': parent_criteria.id if parent_criteria else None,
                    'auto_approved': auto_approve},
            request=request,
        )

        if auto_approve:
            messages.success(request, f'Criteria "{name}" created and approved.')
        else:
            messages.success(request, f'Criteria "{name}" created as draft.')
        return redirect('progress_criteria_list')


# ---------------------------------------------------------------------------
# Submit / Approve / Reject workflow
# ---------------------------------------------------------------------------

class ProgressCriteriaSubmitView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Submit a draft criteria for senior-teacher approval."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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

        log_event(
            user=request.user, school=criteria.school, category='data_change',
            action='progress_criteria_submitted',
            detail={'criteria_id': criteria.id, 'name': criteria.name,
                    'subject': criteria.subject.name if criteria.subject else None,
                    'level': criteria.level.display_name if criteria.level else None},
            request=request,
        )

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
                    f'({_criteria_scope_label(criteria)}) '
                    f'for approval.'
                ),
                notification_type='criteria_approval',
                link=f'/classroom/progress/criteria/approval/',
            )

        messages.success(request, f'Criteria "{criteria.name}" submitted for approval.')
        return redirect('progress_criteria_list')


class ProgressCriteriaApprovalListView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """List criteria pending approval for the current school."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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
        paginator = Paginator(criteria, 25)
        page = paginator.get_page(request.GET.get('page'))

        return render(request, 'progress/criteria_approval.html', {
            'school': school,
            'criteria': page,
            'page': page,
        })


class ProgressCriteriaApproveView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Approve a pending criteria."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = [
        Role.SENIOR_TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def post(self, request, criteria_id):
        criteria = get_object_or_404(ProgressCriteria, pk=criteria_id)

        if criteria.status != 'pending_approval':
            messages.error(request, 'Only pending criteria can be approved.')
            return redirect('progress_criteria_approvals')

        criteria.status = 'approved'
        criteria.approved_by = request.user
        criteria.save()

        log_event(
            user=request.user, school=criteria.school, category='data_change',
            action='progress_criteria_approved',
            detail={'criteria_id': criteria.id, 'name': criteria.name,
                    'subject': criteria.subject.name if criteria.subject else None,
                    'level': criteria.level.display_name if criteria.level else None,
                    'created_by': criteria.created_by.username if criteria.created_by else None},
            request=request,
        )

        # Notify the creator
        if criteria.created_by:
            create_notification(
                user=criteria.created_by,
                message=(
                    f'Your criteria "{criteria.name}" '
                    f'({_criteria_scope_label(criteria)}) '
                    f'has been approved by '
                    f'{request.user.get_full_name() or request.user.username}.'
                ),
                notification_type='criteria_approved',
                link=f'/classroom/progress/criteria/',
            )

        messages.success(request, f'Criteria "{criteria.name}" approved.')
        return redirect('progress_criteria_approvals')


class ProgressCriteriaRejectView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Reject a pending criteria."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = [
        Role.SENIOR_TEACHER, Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_INSTITUTE, Role.INSTITUTE_OWNER,
    ]

    def post(self, request, criteria_id):
        criteria = get_object_or_404(ProgressCriteria, pk=criteria_id)

        if criteria.status != 'pending_approval':
            messages.error(request, 'Only pending criteria can be rejected.')
            return redirect('progress_criteria_approvals')

        criteria.status = 'rejected'
        criteria.save()

        log_event(
            user=request.user, school=criteria.school, category='data_change',
            action='progress_criteria_rejected',
            detail={'criteria_id': criteria.id, 'name': criteria.name,
                    'subject': criteria.subject.name if criteria.subject else None,
                    'level': criteria.level.display_name if criteria.level else None,
                    'created_by': criteria.created_by.username if criteria.created_by else None},
            request=request,
        )

        # Notify the creator
        if criteria.created_by:
            create_notification(
                user=criteria.created_by,
                message=(
                    f'Your criteria "{criteria.name}" '
                    f'({_criteria_scope_label(criteria)}) '
                    f'has been rejected by '
                    f'{request.user.get_full_name() or request.user.username}.'
                ),
                notification_type='criteria_rejected',
                link=f'/classroom/progress/criteria/',
            )

        messages.success(request, f'Criteria "{criteria.name}" rejected.')
        return redirect('progress_criteria_approvals')


# ---------------------------------------------------------------------------
# Record progress (standalone page)
# ---------------------------------------------------------------------------

class RecordProgressView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Record (create/update) progress for students in a specific class."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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
            # Include All-Subjects criteria (subject=null) for every class. See §12.6.
            criteria_qs = criteria_qs.filter(
                Q(subject=classroom.subject) | Q(subject__isnull=True)
            )
        if classroom.levels.exists():
            criteria_qs = criteria_qs.filter(
                Q(level__in=classroom.levels.all()) | Q(level__isnull=True)
            )

        criteria_qs = criteria_qs.select_related('subject', 'level', 'parent').order_by(
            'subject__name', 'level__level_number', 'order', 'name',
        )

        hierarchical_criteria = _build_hierarchical_criteria(criteria_qs)

        from accounts.models import CustomUser
        active_ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)
        students = CustomUser.objects.filter(id__in=active_ids).order_by('last_name', 'first_name', 'username')

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

        # Prefill each student's general comment for this class's subject (latest one),
        # so teachers can add/update a comment right here while recording progress.
        comment_map = {}
        for c in ProgressReportComment.objects.filter(
            student__in=students, school=classroom.school,
            subject=classroom.subject, term__isnull=True,
        ).order_by('student_id', '-created_at'):
            comment_map.setdefault(c.student_id, c.body)

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
                'comment': comment_map.get(student.id, ''),
            })

        return render(request, 'progress/record_progress.html', {
            'classroom': classroom,
            'hierarchical_criteria': hierarchical_criteria,
            'student_rows': student_rows,
            'status_choices': ProgressRecord.STATUS_CHOICES,
        })

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, pk=class_id)
        from accounts.models import CustomUser
        active_ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)
        students = CustomUser.objects.filter(id__in=active_ids)

        criteria_qs = ProgressCriteria.objects.filter(
            school=classroom.school,
            status='approved',
        )
        if classroom.subject:
            # Include All-Subjects criteria (subject=null) for every class. See §12.6.
            criteria_qs = criteria_qs.filter(
                Q(subject=classroom.subject) | Q(subject__isnull=True)
            )
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

        # Save per-student comments (general comment scoped to the class subject).
        # Update the latest existing one if the text changed, else create; blank is
        # left untouched so clearing a box never deletes history.
        comments_saved = 0
        for student in students:
            body = request.POST.get(f'comment_{student.id}', '').strip()
            if not body:
                continue
            existing = (
                ProgressReportComment.objects
                .filter(student=student, school=classroom.school,
                        subject=classroom.subject, term__isnull=True)
                .order_by('-created_at').first()
            )
            if existing is None:
                ProgressReportComment.objects.create(
                    student=student, school=classroom.school,
                    subject=classroom.subject, body=body, created_by=request.user,
                )
                comments_saved += 1
            elif existing.body != body:
                existing.body = body
                existing.updated_by = request.user
                existing.save(update_fields=['body', 'updated_by', 'updated_at'])
                comments_saved += 1

        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='student_progress_recorded',
            detail={'classroom_id': classroom.id, 'classroom_name': classroom.name,
                    'records_updated': updated, 'comments_saved': comments_saved},
            request=request,
        )
        msg = f'Progress updated for {updated} record(s).'
        if comments_saved:
            msg += f' {comments_saved} comment(s) saved.'
        messages.success(request, msg)
        return redirect('record_progress', class_id=class_id)


# ---------------------------------------------------------------------------
# Student progress view
# ---------------------------------------------------------------------------

class StudentProgressView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Show a student's progress records grouped by subject + level."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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

        grouped_progress, overall = _build_student_progress(student)

        # ── Teacher comments + report controls ──────────────────────────
        school = _school_for_student(request, student)
        can_comment = _is_teacher(request.user)

        terms = []
        selected_term = None
        comments = ProgressReportComment.objects.none()
        reports = ProgressReport.objects.none()
        subjects = []
        if school is not None:
            terms = list(Term.objects.filter(school=school))
            term_id = request.GET.get('term')
            if term_id:
                selected_term = next((t for t in terms if str(t.id) == str(term_id)), None)

            comment_qs = ProgressReportComment.objects.filter(
                student=student, school=school,
            ).select_related('term', 'subject', 'created_by', 'updated_by')
            if selected_term is not None:
                comment_qs = comment_qs.filter(term=selected_term)
            comments = comment_qs

            if can_comment:
                reports = ProgressReport.objects.filter(
                    student=student, school=school,
                ).select_related('term', 'generated_by', 'sent_by')[:10]
                subject_ids = ClassStudent.objects.filter(
                    student=student, is_active=True, classroom__school=school,
                ).exclude(classroom__subject__isnull=True).values_list(
                    'classroom__subject_id', flat=True,
                ).distinct()
                subjects = Subject.objects.filter(id__in=subject_ids).order_by('name')

        return render(request, 'progress/student_progress.html', {
            'student': student,
            'grouped_progress': grouped_progress,
            'overall': overall,
            'school': school,
            'can_comment': can_comment,
            'terms': terms,
            'selected_term': selected_term,
            'comments': comments,
            'reports': reports,
            'subjects': subjects,
        })


# ---------------------------------------------------------------------------
# Student Progress Report (overview across all students)
# ---------------------------------------------------------------------------

class StudentProgressReportView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Show a filterable list of students with their progress summary.

    Role-based access:
    - HoI/Institute Owner: all students in all schools they own
    - HoD: students in their department classes + classes they teach
    - Teachers: students in classes they teach
    """
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
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

        subject_ids = accessible_classes.exclude(subject__isnull=True).values_list('subject_id', flat=True).distinct()
        subjects = Subject.objects.filter(id__in=subject_ids, is_active=True).order_by('name')

        classes = accessible_classes.select_related('department', 'subject').order_by('name')

        # Apply filters
        filter_dept = request.GET.get('department')
        filter_subject = request.GET.get('subject')
        filter_class = request.GET.get('classroom')

        filtered_classes = accessible_classes
        if filter_dept:
            filtered_classes = filtered_classes.filter(department_id=filter_dept)
        if filter_subject:
            filtered_classes = filtered_classes.filter(subject_id=filter_subject)
        if filter_class:
            filtered_classes = filtered_classes.filter(id=filter_class)

        # Get students in filtered classes
        student_ids = ClassStudent.objects.filter(
            classroom__in=filtered_classes, is_active=True,
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
            # 'achieved' = proficient (Confident+Advanced); 'in_progress' =
            # developing (Beginning+Developing). See §12.7.
            achieved = sum(1 for r in records if r.status in ProgressRecord.PROFICIENT_STATUSES)
            in_progress_count = sum(1 for r in records if r.status in ProgressRecord.DEVELOPING_STATUSES)
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


# ---------------------------------------------------------------------------
# Progress report comments (teacher add / edit / delete)
# ---------------------------------------------------------------------------

def _student_progress_redirect(student_id, term_id=None):
    """Redirect helper that preserves the selected term in the query string."""
    url = redirect('student_progress', student_id=student_id)
    if term_id:
        url['Location'] = f"{url['Location']}?term={term_id}"
    return url


class ProgressReportCommentCreateView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Teacher adds a narrative comment to a student's progress report."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def post(self, request, student_id):
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, pk=student_id)
        school = _school_for_student(request, student)
        if school is None:
            messages.error(request, 'No school context found for this student.')
            return _student_progress_redirect(student_id)

        body = request.POST.get('body', '').strip()
        term_id = request.POST.get('term') or None
        subject_id = request.POST.get('subject') or None

        if not body:
            messages.error(request, 'Comment cannot be empty.')
            return _student_progress_redirect(student_id, term_id)

        term = Term.objects.filter(pk=term_id, school=school).first() if term_id else None
        subject = Subject.objects.filter(pk=subject_id).first() if subject_id else None

        comment = ProgressReportComment.objects.create(
            student=student,
            school=school,
            term=term,
            subject=subject,
            body=body,
            created_by=request.user,
        )
        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_comment_created',
            detail={'comment_id': comment.id, 'student_id': student.id,
                    'term': term.name if term else None,
                    'subject': subject.name if subject else None},
            request=request,
        )
        messages.success(request, 'Comment added.')
        return _student_progress_redirect(student_id, term_id)


class ProgressReportCommentEditView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Teacher edits/updates an existing progress comment."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def post(self, request, comment_id):
        comment = get_object_or_404(ProgressReportComment, pk=comment_id)
        body = request.POST.get('body', '').strip()
        if not body:
            messages.error(request, 'Comment cannot be empty.')
            return _student_progress_redirect(comment.student_id, comment.term_id)

        comment.body = body
        comment.updated_by = request.user
        comment.save(update_fields=['body', 'updated_by', 'updated_at'])

        log_event(
            user=request.user, school=comment.school, category='data_change',
            action='progress_comment_edited',
            detail={'comment_id': comment.id, 'student_id': comment.student_id},
            request=request,
        )
        messages.success(request, 'Comment updated.')
        return _student_progress_redirect(comment.student_id, comment.term_id)


class ProgressReportCommentDeleteView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Teacher deletes a progress comment."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def post(self, request, comment_id):
        comment = get_object_or_404(ProgressReportComment, pk=comment_id)
        student_id = comment.student_id
        term_id = comment.term_id
        log_event(
            user=request.user, school=comment.school, category='data_change',
            action='progress_comment_deleted',
            detail={'comment_id': comment.id, 'student_id': student_id},
            request=request,
        )
        comment.delete()
        messages.success(request, 'Comment deleted.')
        return _student_progress_redirect(student_id, term_id)


# ---------------------------------------------------------------------------
# Progress report generate / view / send
# ---------------------------------------------------------------------------

def _report_parents(student, school):
    """Active parent/guardian links for a student, scoped to the school."""
    return (
        ParentStudent.objects
        .filter(student=student, is_active=True)
        .filter(Q(school=school) | Q(school__isnull=True))
        .select_related('parent')
    )


def _summary_selection_kwargs(params):
    """Translate the builder's section checkboxes (POST or GET) into
    build_summary() kwargs. Homework/Worksheets each carry a mode and, for
    'selected', the list of item ids picked for the class (see §12.8)."""
    def ids(name):
        return [int(i) for i in params.getlist(name) if str(i).isdigit()]
    return dict(
        homework=bool(params.get('include_homework')),
        homework_mode=params.get('homework_mode') or 'summary',
        homework_ids=ids('homework_ids'),
        worksheets=bool(params.get('include_worksheets')),
        worksheet_mode=params.get('worksheet_mode') or 'summary',
        worksheet_ids=ids('worksheet_ids'),
        maths=bool(params.get('include_maths')),
        maths_times_tables=bool(params.get('include_maths_times_tables')),
        maths_topics=bool(params.get('include_maths_topics')),
        maths_basic_facts=bool(params.get('include_maths_basic_facts')),
        coding=bool(params.get('include_coding')),
        coding_mode=params.get('coding_mode') or 'summary',
        coding_language_ids=ids('coding_language_ids'),
    )


def _apply_report_selection(report, request, classroom=None):
    """Persist the staff section selection + snapshot the cross-app summary.

    Reads the "include this section" checkboxes (see §12.8). The rubric defaults
    to on; the other sections are opt-in. The cross-app numbers are snapshotted
    onto the report so the report and the dashboard card stay consistent even as
    the underlying data changes. The snapshot is the single source of truth the
    templates render (a section appears iff its key is present).
    """
    sel = _summary_selection_kwargs(request.POST)
    report.include_rubric = bool(request.POST.get('include_rubric'))
    report.include_homework = sel['homework']
    report.include_maths = sel['maths']
    report.include_coding = sel['coding']
    if classroom is not None:
        report.classroom = classroom
    report.summary_snapshot = build_summary(report.student, report.classroom, **sel)
    report.save()


class ProgressReportGenerateView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Generate (or refresh) a draft progress report for a single student + term."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def post(self, request, student_id):
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, pk=student_id)
        school = _school_for_student(request, student)
        if school is None:
            messages.error(request, 'No school context found for this student.')
            return _student_progress_redirect(student_id)

        term_id = request.POST.get('term') or None
        term = Term.objects.filter(pk=term_id, school=school).first() if term_id else None

        classroom = None
        class_id = request.POST.get('classroom') or None
        if class_id:
            classroom = ClassRoom.objects.filter(pk=class_id, school=school).first()

        # Reuse an existing draft for this student/term if present, else create.
        report = (
            ProgressReport.objects
            .filter(student=student, school=school, term=term, status=ProgressReport.STATUS_DRAFT)
            .first()
        )
        if report is None:
            report = ProgressReport.objects.create(
                student=student, school=school, term=term,
                generated_by=request.user,
            )
        _apply_report_selection(report, request, classroom=classroom)

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_report_generated',
            detail={'report_id': report.id, 'student_id': student.id,
                    'term': term.name if term else None,
                    'sections': _report_sections(report)},
            request=request,
        )
        return redirect('progress_report_detail', report_id=report.id)


def _report_sections(report):
    """Compact list of the sections a report includes — for logging/UI.

    Reads the snapshot (the source of truth) so it covers worksheets and any
    section without a dedicated model flag.
    """
    snap = report.summary_snapshot or {}
    flags = [
        ('rubric', report.include_rubric),
        ('homework', 'homework' in snap), ('worksheets', 'worksheets' in snap),
        ('maths', 'maths' in snap), ('coding', 'coding' in snap),
    ]
    return [name for name, on in flags if on]


class ProgressReportClassBuilderView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Per-class report builder: pick sections once, generate a report per student."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def _students(self, classroom):
        from accounts.models import CustomUser
        ids = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).values_list('student_id', flat=True)
        return CustomUser.objects.filter(id__in=ids).order_by(
            'last_name', 'first_name', 'username',
        )

    def get(self, request, class_id):
        from homework.models import Homework
        from worksheets.models import WorksheetAssignment
        from coding.models import CodingLanguage
        classroom = get_object_or_404(ClassRoom, pk=class_id)
        terms = Term.objects.filter(school=classroom.school).order_by('-start_date')
        coding_languages = CodingLanguage.objects.order_by('order', 'name').values('id', 'name')
        homeworks = Homework.objects.filter(
            classroom=classroom, published_at__isnull=False,
        ).order_by('-due_date').values('id', 'title')
        worksheets = WorksheetAssignment.objects.filter(
            classroom=classroom, is_active=True,
        ).select_related('worksheet').order_by('-assigned_at')
        return render(request, 'progress/report_class_builder.html', {
            'classroom': classroom,
            'students': self._students(classroom),
            'terms': terms,
            'homeworks': homeworks,
            'worksheets': [
                {'id': a.id, 'title': a.worksheet.name} for a in worksheets
            ],
            'coding_languages': coding_languages,
        })

    def post(self, request, class_id):
        classroom = get_object_or_404(ClassRoom, pk=class_id)
        school = classroom.school
        term_id = request.POST.get('term') or None
        term = Term.objects.filter(pk=term_id, school=school).first() if term_id else None

        students = self._students(classroom)
        count = 0
        for student in students:
            report = (
                ProgressReport.objects
                .filter(student=student, school=school, term=term,
                        status=ProgressReport.STATUS_DRAFT)
                .first()
            )
            if report is None:
                report = ProgressReport.objects.create(
                    student=student, school=school, term=term,
                    generated_by=request.user,
                )
            _apply_report_selection(report, request, classroom=classroom)
            count += 1

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_reports_class_generated',
            detail={'classroom_id': classroom.id, 'count': count,
                    'term': term.name if term else None},
            request=request,
        )
        messages.success(
            request,
            f'Generated {count} draft report{"" if count == 1 else "s"} for {classroom.name}.',
        )
        return redirect('student_progress_report')


class ProgressReportPreviewView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Live, unsaved preview of one student's report for the builder's current
    section selection (passed as GET params). Nothing is persisted — staff use it
    to check each student before generating drafts (§12.8)."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def get(self, request, student_id):
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, pk=student_id)
        school = _school_for_student(request, student)

        class_id = request.GET.get('classroom') or None
        classroom = ClassRoom.objects.filter(pk=class_id).first() if class_id else None

        sel = _summary_selection_kwargs(request.GET)
        report = ProgressReport(
            student=student, school=school, classroom=classroom,
            include_rubric=bool(request.GET.get('include_rubric')),
            include_homework=sel['homework'], include_maths=sel['maths'],
            include_coding=sel['coding'],
            summary_snapshot=build_summary(student, classroom, **sel),
        )
        grouped_progress, overall = _build_student_progress(student)
        return render(request, 'progress/report_preview.html', {
            'report': report, 'student': student, 'school': school,
            'grouped_progress': grouped_progress, 'overall': overall,
        })


class ProgressReportDetailView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Printable progress report with a 'Send to parents' button."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def get(self, request, report_id):
        report = get_object_or_404(
            ProgressReport.objects.select_related('student', 'school', 'term', 'sent_by'),
            pk=report_id,
        )
        grouped_progress, overall = _build_student_progress(report.student)

        comments = ProgressReportComment.objects.filter(
            student=report.student, school=report.school,
        ).select_related('term', 'subject', 'created_by')
        if report.term_id:
            comments = comments.filter(Q(term=report.term) | Q(term__isnull=True))

        parents = _report_parents(report.student, report.school)

        return render(request, 'progress/report_detail.html', {
            'report': report,
            'student': report.student,
            'school': report.school,
            'term': report.term,
            'grouped_progress': grouped_progress,
            'overall': overall,
            'comments': comments,
            'parents': parents,
        })


class ProgressReportSendView(RoleRequiredMixin, ModuleRequiredMixin, View):
    """Email the generated report to the student's linked parents/guardians."""
    required_module = ModuleSubscription.MODULE_PROGRESS_REPORTS
    required_roles = TEACHER_ROLES

    def post(self, request, report_id):
        report = get_object_or_404(
            ProgressReport.objects.select_related('student', 'school', 'term'),
            pk=report_id,
        )
        student = report.student
        school = report.school

        grouped_progress, overall = _build_student_progress(student)
        comments = ProgressReportComment.objects.filter(
            student=student, school=school,
        ).select_related('term', 'subject', 'created_by')
        if report.term_id:
            comments = comments.filter(Q(term=report.term) | Q(term__isnull=True))
        comments = list(comments)

        parents = _report_parents(student, school)
        if not parents.exists():
            messages.error(
                request,
                'This student has no linked parents/guardians to send the report to.',
            )
            return redirect('progress_report_detail', report_id=report.id)

        from .email_service import send_templated_email
        report_link = f'/classroom/progress/student/{student.id}/'
        if report.term_id:
            report_link += f'?term={report.term_id}'
        student_name = student.get_full_name() or student.username
        term_label = report.term.name if report.term else 'this term'

        sent_count = 0
        seen_emails = set()
        for link in parents:
            parent = link.parent
            email = (parent.email or '').strip()
            if not email or email.lower() in seen_emails:
                continue
            seen_emails.add(email.lower())

            ok = send_templated_email(
                recipient_email=email,
                subject=f'{student_name} — Progress Report ({term_label})',
                template_name='email/transactional/progress_report.html',
                context={
                    'student_name': student_name,
                    'school_name': school.name,
                    'term_label': term_label,
                    'report': report,
                    'overall': overall,
                    'grouped_progress': grouped_progress,
                    'comments': comments,
                    'report_link': report_link,
                },
                recipient_user=parent,
                notification_type='progress_report',
                school=school,
            )
            if ok:
                sent_count += 1

            # In-app notification (email already sent above).
            create_notification(
                user=parent,
                message=(
                    f"A progress report for {student_name} ({term_label}) "
                    f"has been shared with you."
                ),
                notification_type='progress_report',
                link=report_link,
                send_email=False,
            )

        report.status = ProgressReport.STATUS_SENT
        report.sent_by = request.user
        report.sent_at = timezone.now()
        report.recipient_count = sent_count
        report.save(update_fields=['status', 'sent_by', 'sent_at', 'recipient_count'])

        log_event(
            user=request.user, school=school, category='data_change',
            action='progress_report_sent',
            detail={'report_id': report.id, 'student_id': student.id,
                    'term': report.term.name if report.term else None,
                    'recipients': sent_count},
            request=request,
        )
        messages.success(
            request,
            f'Progress report sent to {sent_count} parent(s)/guardian(s).',
        )
        return redirect('progress_report_detail', report_id=report.id)
