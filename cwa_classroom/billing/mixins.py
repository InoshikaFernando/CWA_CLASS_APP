"""
Subscription and module enforcement mixins for views.

Multi-school design:
  Students can be enrolled in multiple institutes. Module and plan checks
  use ANY-school logic: if a student is in School A (which has the module)
  and School B (which doesn't), the student can still access the feature.
  Plan limits (classes, students) are always per-school since they are the
  school admin's responsibility.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect

from billing.entitlements import (
    get_school_subscription, has_module, has_module_any_school,
    get_school_for_user, any_school_has_active_subscription,
)


class _SchoolResolverMixin:
    """Shared logic for resolving a school from the request context."""

    def _resolve_school(self, request, *args, **kwargs):
        """
        Resolve the school from the request context.
        Override in subclasses if the school is available via URL kwargs.
        """
        # Try from URL kwargs
        school_id = kwargs.get('school_id')
        if school_id:
            from classroom.models import School
            try:
                return School.objects.get(pk=school_id)
            except School.DoesNotExist:
                pass

        # Try from session
        school_id = request.session.get('current_school_id')
        if school_id:
            from classroom.models import School
            try:
                return School.objects.get(pk=school_id)
            except School.DoesNotExist:
                pass

        # Fallback to user's primary school
        return get_school_for_user(request.user)


class PlanRequiredMixin(_SchoolResolverMixin):
    """
    Mixin that checks if the user's school has an active subscription.
    For multi-school students, allows access if ANY school has an active sub.
    """

    def dispatch(self, request, *args, **kwargs):
        school = self._resolve_school(request, *args, **kwargs)
        if school:
            sub = get_school_subscription(school)
            if sub and not sub.is_active_or_trialing:
                # Multi-school check: maybe another school is active
                if not any_school_has_active_subscription(request.user):
                    from audit.services import log_event
                    log_event(
                        user=request.user, school=school,
                        category='entitlement', action='subscription_expired_access',
                        result='blocked', request=request,
                    )
                    messages.warning(
                        request,
                        'Your school subscription has expired. '
                        'Please subscribe to continue using this feature.',
                    )
                    return redirect('institute_trial_expired')
        return super().dispatch(request, *args, **kwargs)


class ModuleRequiredMixin(_SchoolResolverMixin):
    """
    Mixin that checks if the user's school has a specific module enabled.
    For multi-school students, allows access if ANY school has the module.

    Usage:
        class MyView(RoleRequiredMixin, ModuleRequiredMixin, View):
            required_module = 'teachers_attendance'
    """
    required_module = None  # e.g., 'teachers_attendance'

    def dispatch(self, request, *args, **kwargs):
        if self.required_module:
            school = self._resolve_school(request, *args, **kwargs)
            if school and not has_module(school, self.required_module):
                # Multi-school fallback: check all schools the user belongs to
                if not has_module_any_school(request.user, self.required_module):
                    from audit.services import log_event
                    log_event(
                        user=request.user, school=school,
                        category='entitlement', action='module_access_denied',
                        result='blocked',
                        detail={'module': self.required_module},
                        request=request,
                    )
                    from django.urls import reverse
                    url = reverse('module_required') + '?' + urlencode({
                        'module': self.required_module,
                    })
                    return redirect(url)
        return super().dispatch(request, *args, **kwargs)
