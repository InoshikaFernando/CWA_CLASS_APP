from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
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
        })
