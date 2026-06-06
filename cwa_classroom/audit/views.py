import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views import View

from accounts.models import Role
from classroom.views import RoleRequiredMixin

logger = logging.getLogger(__name__)


# ---- Roles shown in the activity summary (excludes internal/admin roles) ----
_SUMMARY_ROLES = [Role.TEACHER, Role.PARENT, Role.STUDENT]


# ---- Action-history access control ----
# Any staff member can see their own action history.
STAFF_ROLES = [
    Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
    Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
]
_ELEVATED = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]
_MANAGER = _ELEVATED + [Role.HEAD_OF_DEPARTMENT]

# Reverting a privileged action requires the user to STILL hold an appropriate
# role at revert time — not merely to have performed it once. Actions absent
# from this map fall back to STAFF_ROLES (any staff may revert their own).
ACTION_REQUIRED_ROLES = {
    'school_toggled_active': _ELEVATED,
    'user_blocked': _ELEVATED,
    'user_unblocked': _ELEVATED,
    'parent_student_unlinked': _ELEVATED,
    'student_fee_updated': _ELEVATED,
    'student_removed': _ELEVATED,
    'student_restored': _ELEVATED,
    'teacher_removed': _ELEVATED,
    'teacher_restored': _ELEVATED,
    'billing_plan_toggled': [Role.ADMIN],
    'discount_code_toggled': [Role.ADMIN],
    'subject_archived': _MANAGER,
    'subject_restored': _MANAGER,
    'department_toggled_active': _MANAGER,
    'hod_class_deleted': _MANAGER,
    'hod_class_restored': _MANAGER,
}


def _user_role_names(user):
    """Set of the user's current role names (single query)."""
    return set(user.user_roles.values_list('role__name', flat=True))


def _can_revert_action(role_names, action):
    """True if the user's current roles satisfy the action's revert requirement."""
    required = ACTION_REQUIRED_ROLES.get(action, STAFF_ROLES)
    return not role_names.isdisjoint(required)


def _get_role_activity_summary(school_ids=None, days=7):
    """
    Return a list of dicts: [{role_name, display_name, count}, ...] for the
    last *days* days, optionally scoped to a set of schools.
    """
    from .models import AuditLog

    cutoff = timezone.now() - timedelta(days=days)
    qs = AuditLog.objects.filter(created_at__gte=cutoff)
    if school_ids is not None:
        qs = qs.filter(school_id__in=school_ids)

    counts = dict(
        qs.filter(user__user_roles__role__name__in=_SUMMARY_ROLES)
        .values_list('user__user_roles__role__name')
        .annotate(c=Count('id'))
        .values_list('user__user_roles__role__name', 'c')
    )

    display_map = dict(
        Role.objects.filter(name__in=_SUMMARY_ROLES)
        .values_list('name', 'display_name')
    )

    return [
        {
            'role_name': r,
            'display_name': display_map.get(r, r.replace('_', ' ').title()),
            'count': counts.get(r, 0),
        }
        for r in _SUMMARY_ROLES
    ]


def _get_top_actions(qs, limit=5):
    """Return the top *limit* actions from a queryset as [(action, count), ...]."""
    return list(
        qs.values('action')
        .annotate(c=Count('id'))
        .order_by('-c')
        .values_list('action', 'c')[:limit]
    )


class AuditDashboardView(RoleRequiredMixin, View):
    """Admin-only dashboard showing risk summary, role activity, and recent events."""
    required_roles = [Role.ADMIN]

    def get(self, request):
        from .risk import get_risk_summary
        from .models import AuditLog

        summary = get_risk_summary()
        recent_events = AuditLog.objects.select_related('user', 'school').order_by('-created_at')[:50]
        role_summary = _get_role_activity_summary()

        return render(request, 'audit/dashboard.html', {
            'summary': summary,
            'recent_events': recent_events,
            'role_summary': role_summary,
        })


class AuditLogListView(RoleRequiredMixin, View):
    """Legacy audit log list — redirects to the superior EventsView."""
    required_roles = [Role.ADMIN]

    def get(self, request):
        # Preserve query parameters in redirect
        query_string = request.META.get('QUERY_STRING', '')
        url = '/audit/events/'
        if query_string:
            url += '?' + query_string
        return redirect(url, permanent=False)


class EventsView(RoleRequiredMixin, View):
    """Events page accessible to superusers (all schools) and HoI (own school)."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    PAGE_SIZE = 50

    def get(self, request):
        from .models import AuditLog
        from classroom.models import School, SchoolTeacher

        qs = AuditLog.objects.select_related('user', 'school').prefetch_related(
            'user__user_roles__role',
        ).order_by('-created_at')

        is_superuser = request.user.is_superuser

        # School scoping
        if is_superuser:
            schools_list = School.objects.filter(is_active=True).order_by('name')
            selected_schools = request.GET.getlist('schools')
            if selected_schools:
                qs = qs.filter(school_id__in=selected_schools)
        else:
            # HoI: restrict to their school(s)
            admin_school_ids = set(
                School.objects.filter(admin=request.user, is_active=True)
                .values_list('id', flat=True)
            )
            hoi_school_ids = set(
                SchoolTeacher.objects.filter(
                    teacher=request.user, role='head_of_institute', is_active=True,
                ).values_list('school_id', flat=True)
            )
            user_school_ids = admin_school_ids | hoi_school_ids
            qs = qs.filter(school_id__in=user_school_ids)
            schools_list = School.objects.filter(id__in=user_school_ids).order_by('name')
            selected_schools = []

        # Filters
        category = request.GET.get('category', '')
        action = request.GET.get('action', '')
        result = request.GET.get('result', '')
        date_from = request.GET.get('date_from', '')
        date_to = request.GET.get('date_to', '')
        role = request.GET.get('role', '')

        if category:
            qs = qs.filter(category=category)
        if action:
            qs = qs.filter(action__icontains=action)
        if result:
            qs = qs.filter(result=result)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if role:
            qs = qs.filter(user__user_roles__role__name=role)

        # Roles for dropdown
        roles_list = Role.objects.filter(is_active=True).order_by('display_name')

        # Top actions (for current filtered queryset)
        top_actions = _get_top_actions(qs)

        # Pagination
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_number = request.GET.get('page', 1)
        try:
            page = paginator.page(page_number)
        except Exception:
            page = paginator.page(1)

        return render(request, 'audit/events.html', {
            'page': page,
            'is_superuser': is_superuser,
            'schools_list': schools_list,
            'selected_schools': selected_schools,
            'categories': AuditLog.CATEGORY_CHOICES,
            'roles_list': roles_list,
            'category': category,
            'action': action,
            'result': result,
            'date_from': date_from,
            'date_to': date_to,
            'role': role,
            'top_actions': top_actions,
        })


class ActionHistoryView(LoginRequiredMixin, View):
    """My Action History -- shows the logged-in staff member's recent actions."""

    PAGE_SIZE = 50

    def get(self, request):
        from .models import AuditLog
        from .reverters import ACTION_LABELS, REVERTIBLE_ACTIONS

        role_names = _user_role_names(request.user)
        if role_names.isdisjoint(STAFF_ROLES):
            messages.warning(request, 'Action history is only available to staff.')
            return redirect('home')

        qs = (
            AuditLog.objects
            .filter(user=request.user, category__in=['data_change', 'admin_action'])
            .select_related('school')
            .order_by('-created_at')
        )

        paginator = Paginator(qs, self.PAGE_SIZE)
        page_number = request.GET.get('page', 1)
        try:
            page = paginator.page(page_number)
        except Exception:
            page = paginator.page(1)

        for entry in page.object_list:
            entry.display_label = ACTION_LABELS.get(
                entry.action, entry.action.replace('_', ' ').title(),
            )
            entry.can_revert = (
                entry.is_revertible
                and entry.reverted_at is None
                and entry.action in REVERTIBLE_ACTIONS
                and _can_revert_action(role_names, entry.action)
            )
            if entry.can_revert:
                _, entry.revert_label = REVERTIBLE_ACTIONS[entry.action]

        return render(request, 'audit/action_history.html', {
            'page': page,
        })


class RevertActionView(LoginRequiredMixin, View):
    """POST-only endpoint to revert a single audit log entry."""

    def post(self, request, log_id):
        from .models import AuditLog
        from .reverters import REVERTIBLE_ACTIONS
        from .services import log_event

        role_names = _user_role_names(request.user)
        if role_names.isdisjoint(STAFF_ROLES):
            messages.error(request, 'Permission denied.')
            return redirect('action_history')

        entry = get_object_or_404(AuditLog, id=log_id, user=request.user)

        if entry.reverted_at is not None:
            messages.info(request, 'This action has already been reverted.')
            return redirect('action_history')

        if entry.action not in REVERTIBLE_ACTIONS:
            messages.error(request, 'This action cannot be reverted.')
            return redirect('action_history')

        # Re-validate privilege at revert time, not just at action time.
        if not _can_revert_action(role_names, entry.action):
            messages.error(request, 'You no longer have permission to revert this action.')
            return redirect('action_history')

        reverter_fn, label = REVERTIBLE_ACTIONS[entry.action]
        try:
            reverter_fn(entry)
        except Exception:
            logger.exception('Failed to revert audit log %d', entry.id)
            messages.error(
                request,
                'Failed to revert this action. The data may have changed since.',
            )
            return redirect('action_history')

        entry.reverted_at = timezone.now()
        entry.reverted_by = request.user
        entry.save(update_fields=['reverted_at', 'reverted_by'])

        log_event(
            user=request.user,
            school=entry.school,
            category='admin_action',
            action='action_reverted',
            detail={
                'reverted_log_id': entry.id,
                'reverted_action': entry.action,
                'original_detail': entry.detail,
            },
            request=request,
        )

        messages.success(request, 'Reverted: ' + label)
        return redirect('action_history')