from django.contrib import admin

from taskqueue.models import AIUsageLog, BackgroundTask


@admin.register(BackgroundTask)
class BackgroundTaskAdmin(admin.ModelAdmin):
    list_display = ['task_type', 'status', 'school', 'created_by', 'created_at', 'completed_at']
    list_filter = ['status', 'task_type']
    search_fields = ['rq_job_id', 'school__name', 'created_by__username']
    readonly_fields = ['rq_job_id', 'result_data', 'error_message', 'created_at', 'completed_at']
    raw_id_fields = ['school', 'created_by']


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = [
        'created_at', 'source', 'school', 'pages',
        'input_tokens', 'output_tokens', 'total_tokens', 'est_cost_usd',
        'cost_per_page_display',
    ]
    list_filter = ['source', 'created_at']
    search_fields = ['school__name', 'session_id']
    readonly_fields = [
        'school', 'source', 'session_id', 'pages',
        'input_tokens', 'output_tokens', 'est_cost_usd', 'created_at',
    ]
    raw_id_fields = ['school']
    date_hierarchy = 'created_at'

    @admin.display(description='$/page', ordering='est_cost_usd')
    def cost_per_page_display(self, obj):
        cpp = obj.cost_per_page_usd
        return f'${cpp:.4f}' if cpp is not None else '—'
