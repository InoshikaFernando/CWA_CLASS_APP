from django.contrib import admin

from taskqueue.models import BackgroundTask


@admin.register(BackgroundTask)
class BackgroundTaskAdmin(admin.ModelAdmin):
    list_display = ['task_type', 'status', 'school', 'created_by', 'created_at', 'completed_at']
    list_filter = ['status', 'task_type']
    search_fields = ['rq_job_id', 'school__name', 'created_by__username']
    readonly_fields = ['rq_job_id', 'result_data', 'error_message', 'created_at', 'completed_at']
    raw_id_fields = ['school', 'created_by']
