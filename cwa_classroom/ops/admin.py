from django.contrib import admin

from ops import flags

from .models import FeatureFlag, OpsSnapshot


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


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    """Where a feature gets turned on. No deploy, no env var, no restart."""

    list_display = ('slug', 'rollout', 'pilot_schools', 'updated_at')
    list_filter = ('rollout',)
    search_fields = ('slug', 'description')
    filter_horizontal = ('schools',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Pilot schools')
    def pilot_schools(self, obj):
        if obj.rollout != FeatureFlag.PILOT:
            return '—'
        names = list(obj.schools.values_list('name', flat=True))
        return ', '.join(names) if names else '(none — so nobody)'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        flags.invalidate()

    def save_related(self, request, form, formsets, change):
        # The school list is M2M, saved after save_model — invalidating only
        # there would cache the old pilot list for another thirty seconds.
        super().save_related(request, form, formsets, change)
        flags.invalidate()
