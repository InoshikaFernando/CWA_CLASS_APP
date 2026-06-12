from django.contrib import admin

from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'category', 'title', 'submitted_by', 'role', 'school',
        'status', 'priority', 'created_at', 'removed_at',
    )
    list_filter = ('category', 'status', 'priority', 'removed_at')
    search_fields = ('title', 'description', 'submitted_by__username', 'page_url')
    raw_id_fields = ('submitted_by', 'school', 'assignee')
    readonly_fields = ('created_at', 'updated_at')
