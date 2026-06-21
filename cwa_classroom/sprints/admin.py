from django.contrib import admin

from .models import Sprint, SprintSnapshot


class SprintSnapshotInline(admin.TabularInline):
    model = SprintSnapshot
    extra = 0
    readonly_fields = ('snapshot_date', 'remaining_points', 'completed_points',
                       'total_points', 'created_at')
    can_delete = False


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ('name', 'jira_sprint_id', 'state', 'start_date', 'end_date',
                    'committed_points')
    list_filter = ('state',)
    search_fields = ('name', 'jira_sprint_id')
    inlines = [SprintSnapshotInline]


@admin.register(SprintSnapshot)
class SprintSnapshotAdmin(admin.ModelAdmin):
    list_display = ('sprint', 'snapshot_date', 'remaining_points',
                    'completed_points', 'total_points')
    list_filter = ('sprint',)
    date_hierarchy = 'snapshot_date'
