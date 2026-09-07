from django.contrib import admin

from .models import PointsAward, StudentPointsTotal


@admin.register(PointsAward)
class PointsAwardAdmin(admin.ModelAdmin):
    list_display = ('student', 'source', 'unit_key', 'points', 'label', 'updated_at')
    list_filter = ('source',)
    search_fields = ('student__username', 'student__first_name', 'student__last_name', 'label')
    raw_id_fields = ('student',)
    ordering = ('-updated_at',)


@admin.register(StudentPointsTotal)
class StudentPointsTotalAdmin(admin.ModelAdmin):
    list_display = ('student', 'total_points', 'units_completed', 'is_ranked', 'last_earned_at')
    list_filter = ('is_ranked',)
    search_fields = ('student__username', 'student__first_name', 'student__last_name')
    raw_id_fields = ('student',)
    ordering = ('-total_points',)
