"""
Messaging views — compose and schedule email/SMS communications (CPP-348).

Phase 1 (CPP-349): routing + placeholder shell only.
Recipients, scheduling, and send logic come in CPP-350 – CPP-353.
"""
from django.shortcuts import redirect, render
from django.views import View

from accounts.models import Role
from .views import RoleRequiredMixin
from .models import School

_MESSAGING_ROLES = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]


def _get_school(user):
    return School.objects.filter(admin=user).first()


class MessagingDashboardView(RoleRequiredMixin, View):
    """Redirect /messaging/ → compose page (canonical entry point)."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        return redirect('messaging_compose')


class MessagingComposeView(RoleRequiredMixin, View):
    """Compose page shell — CPP-350/351/352/353 fill in the real UI."""
    required_roles = _MESSAGING_ROLES

    def get(self, request):
        school = _get_school(request.user)
        return render(request, 'messaging/compose.html', {'school': school})
