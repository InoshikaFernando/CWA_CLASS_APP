from django.contrib import admin

from .models import PageHit


@admin.register(PageHit)
class PageHitAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'method', 'path', 'status_code', 'user')
    list_filter = ('status_code', 'method', 'created_at')
    search_fields = ('path', 'user__email', 'user__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'path', 'method', 'status_code', 'user', 'session_key')

    def has_add_permission(self, request):
        return False
