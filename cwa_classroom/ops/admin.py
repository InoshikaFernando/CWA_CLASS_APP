from django.contrib import admin

from .models import OpsSnapshot


@admin.register(OpsSnapshot)
class OpsSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'status', 'mem_used_pct', 'disk_used_pct',
        'rq_default', 'rq_high', 'issues',
    )
    list_filter = ('status',)
    date_hierarchy = 'created_at'
    readonly_fields = [f.name for f in OpsSnapshot._meta.fields]

    def has_add_permission(self, request):
        return False  # snapshots are machine-written only
