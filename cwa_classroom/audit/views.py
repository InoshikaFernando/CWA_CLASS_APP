from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.views import View

from accounts.models import Role
from classroom.views import RoleRequiredMixin


class AuditDashboardView(RoleRequiredMixin, View):
    """Admin-only dashboard showing risk summary and recent audit events."""
    required_roles = [Role.ADMIN]

    def get(self, request):
        from .risk import get_risk_summary
        from .models import AuditLog

        summary = get_risk_summary()
        recent_events = AuditLog.objects.select_related('user', 'school').order_by('-created_at')[:50]

        return render(request, 'audit/dashboard.html', {
            'summary': summary,
            'recent_events': recent_events,
        })


class AuditLogListView(RoleRequiredMixin, View):
    """Paginated, filterable audit log list. Admin only."""
    required_roles = [Role.ADMIN]

    PAGE_SIZE = 50

    def get(self, request):
        from .models import AuditLog

        qs = AuditLog.objects.select_related('user', 'school').order_by('-created_at')

        # Filters
        category = request.GET.get('category', '')
        action = request.GET.get('action', '')
        result = request.GET.get('result', '')
        if category:
            qs = qs.filter(category=category)
        if action:
            qs = qs.filter(action__icontains=action)
        if result:
            qs = qs.filter(result=result)

        # Pagination
        page = int(request.GET.get('page', 1))
        offset = (page - 1) * self.PAGE_SIZE
        events = qs[offset:offset + self.PAGE_SIZE + 1]
        has_next = len(events) > self.PAGE_SIZE
        events = events[:self.PAGE_SIZE]

        return render(request, 'audit/log_list.html', {
            'events': events,
            'category': category,
            'action': action,
            'result': result,
            'page': page,
            'has_next': has_next,
            'categories': AuditLog.CATEGORY_CHOICES,
        })
