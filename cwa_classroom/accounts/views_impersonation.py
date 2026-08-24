"""
Super-admin "View as" screens: pick a real user, confirm, browse read-only, stop.

The mechanism itself lives in ``accounts.impersonation``; this module is only
the way in and the way out.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from . import impersonation
from .dashboards import dashboard_for_role
from .models import CustomUser, Role

# Roles worth offering as a filter — the ones whose experience a super admin
# actually wants to check.
PICKER_ROLES = [
    (Role.STUDENT, 'Student'),
    (Role.INDIVIDUAL_STUDENT, 'Student (Individual)'),
    (Role.PARENT, 'Parent'),
    (Role.TEACHER, 'Teacher'),
    (Role.SENIOR_TEACHER, 'Senior Teacher'),
    (Role.JUNIOR_TEACHER, 'Junior Teacher'),
    (Role.HEAD_OF_DEPARTMENT, 'Head of Department'),
    (Role.HEAD_OF_INSTITUTE, 'Head of Institute'),
    (Role.ACCOUNTANT, 'Accountant'),
]

MAX_RESULTS = 25


class SuperuserRequiredMixin(LoginRequiredMixin):
    """Platform super admins only.

    Deliberately ``is_superuser`` and not ``Role.ADMIN``: in this app
    ``Role.ADMIN`` is a school's own administrator, and one tenant's admin must
    never be able to step into another tenant's accounts.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not impersonation.can_impersonate(request.user):
            messages.error(request, "You don't have permission to access that page.")
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)


def _annotate_schools(users):
    """Set ``school_name`` on each user in three queries rather than one per row.

    Django templates can't look a dict up by a variable key, so the name is
    attached to the object instead of returned as a map.
    """
    from classroom.models import ParentStudent, SchoolStudent, SchoolTeacher

    ids = [u.pk for u in users]
    if not ids:
        return users

    schools = {}
    for qs, field in (
        (SchoolStudent.objects.filter(student_id__in=ids, is_active=True), 'student_id'),
        (SchoolTeacher.objects.filter(teacher_id__in=ids, is_active=True), 'teacher_id'),
        (ParentStudent.objects.filter(parent_id__in=ids, is_active=True), 'parent_id'),
    ):
        for user_id, name in qs.values_list(field, 'school__name'):
            schools.setdefault(user_id, name)

    for user in users:
        user.school_name = schools.get(user.pk, '')
    return users


class ImpersonationPickerView(SuperuserRequiredMixin, View):
    """Search for the student / teacher / parent whose view you want to see."""

    def get(self, request):
        query = (request.GET.get('q') or '').strip()
        role = (request.GET.get('role') or '').strip()

        results = []
        # No blanket listing: with thousands of accounts an unfiltered dump is
        # useless to read and expensive to build.
        if query or role:
            qs = CustomUser.objects.filter(
                is_active=True, is_superuser=False, is_staff=False,
            )
            if query:
                qs = qs.filter(
                    Q(username__icontains=query)
                    | Q(email__icontains=query)
                    | Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                )
            if role:
                qs = qs.filter(roles__name=role, roles__is_active=True)
            results = list(
                qs.distinct().prefetch_related('roles').order_by('first_name', 'last_name', 'username')[:MAX_RESULTS]
            )

        return render(request, 'accounts/impersonation_picker.html', {
            'query': query,
            'selected_role': role,
            'picker_roles': PICKER_ROLES,
            'results': _annotate_schools(results),
            'result_limit': MAX_RESULTS,
            'searched': bool(query or role),
        })


class ImpersonationStartView(SuperuserRequiredMixin, View):
    """GET confirms what is about to happen; POST actually switches."""

    def get(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        ok, reason = impersonation.is_impersonatable(target, request.user)
        return render(request, 'accounts/impersonation_confirm.html', {
            'target_user': target,
            'target_role': target.primary_role,
            'blocked_reason': '' if ok else reason,
            'minutes': impersonation.max_seconds() // 60,
        })

    def post(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        ok, reason = impersonation.is_impersonatable(target, request.user)
        if not ok:
            messages.error(request, reason)
            return redirect('impersonation_picker')

        impersonation.start(request, target)
        messages.info(
            request,
            f'You are now viewing the site as {target.get_full_name() or target.username}. '
            f'This session is read-only.',
        )
        return redirect(dashboard_for_role(target.primary_role))


class ImpersonationStopView(LoginRequiredMixin, View):
    """Hand the session back to the real super admin.

    Not gated on ``is_superuser``: while impersonating, ``request.user`` is the
    *target*, so a superuser check here would lock the admin inside the session
    they are trying to leave. The middleware has already proved a real super
    admin is behind it.
    """

    def post(self, request):
        if not getattr(request, 'is_impersonating', False):
            return redirect('home')

        target = impersonation.stop(request)
        name = (target.get_full_name() or target.username) if target else 'that user'
        messages.success(request, f'Stopped viewing as {name}. You are back on your own account.')
        return redirect('impersonation_picker')
