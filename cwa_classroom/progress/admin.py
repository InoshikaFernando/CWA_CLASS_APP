# Progress app is a thin shared utility — most model data lives in each subject's app.
# Maths progress data is managed via maths/admin.py.
#
# The exception is PeriodReport (CPP-388): an end-of-period report is a frozen
# snapshot, so it is stored here and registered so support can see what a family
# was actually sent.

from django.contrib import admin

from .models import PeriodReport


@admin.register(PeriodReport)
class PeriodReportAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'period_type', 'period_start', 'period_end',
        'school', 'notified_at', 'parent_emailed_at',
    )
    list_filter = ('period_type', 'school', 'notified_at')
    search_fields = ('student__username', 'student__first_name', 'student__last_name')
    date_hierarchy = 'period_start'
    autocomplete_fields = ('student',)
    # The snapshot is the record of what was sent — editing it here would make
    # the PDF a family already downloaded disagree with the database.
    readonly_fields = (
        'student', 'school', 'term', 'period_type', 'period_start',
        'period_end', 'data', 'generated_at', 'notified_at', 'parent_emailed_at',
    )

    def has_add_permission(self, request):
        return False
