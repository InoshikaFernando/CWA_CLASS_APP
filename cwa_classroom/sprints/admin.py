from django.contrib import admin

from .models import ProjectSnapshot, Sprint, SprintSnapshot


class SprintSnapshotInline(admin.TabularInline):
    model = SprintSnapshot
    extra = 0
    readonly_fields = ('snapshot_date', 'remaining_points', 'completed_points',
                       'total_points', 'created_at')
    can_delete = False


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ('name', 'jira_sprint_id', 'state', 'start_date', 'end_date',
                    'committed_points', 'baseline_captured')
    list_filter = ('state', 'baseline_captured')
    search_fields = ('name', 'jira_sprint_id')
    inlines = [SprintSnapshotInline]


@admin.register(SprintSnapshot)
class SprintSnapshotAdmin(admin.ModelAdmin):
    list_display = ('sprint', 'snapshot_date', 'remaining_points',
                    'completed_points', 'total_points')
    list_filter = ('sprint',)
    date_hierarchy = 'snapshot_date'


@admin.register(ProjectSnapshot)
class ProjectSnapshotAdmin(admin.ModelAdmin):
    list_display = ('snapshot_date', 'remaining_points', 'completed_points',
                    'total_points', 'open_issue_count', 'updated_at')
    date_hierarchy = 'snapshot_date'
