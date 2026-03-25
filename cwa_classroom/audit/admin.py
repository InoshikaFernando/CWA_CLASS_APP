from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        'action', 'category', 'result', 'user', 'school',
        'ip_address', 'created_at',
    )
    list_filter = ('category', 'result', 'action', 'created_at')
    search_fields = ('user__username', 'school__name', 'action', 'ip_address')
    readonly_fields = (
        'user', 'school', 'category', 'action', 'result',
        'detail', 'ip_address', 'user_agent', 'endpoint', 'created_at',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
