from django.contrib import admin

from .models import ClassSession, StudentAttendance, TeacherAttendance


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ('classroom', 'date', 'start_time', 'end_time', 'status', 'created_by')
    list_filter = ('status', 'classroom__school')
    search_fields = ('classroom__name',)
    date_hierarchy = 'date'
    ordering = ('-date', '-start_time')


@admin.register(StudentAttendance)
class StudentAttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'status', 'self_reported', 'approved_by', 'marked_at')
    list_filter = ('status', 'self_reported')
    search_fields = ('student__username', 'student__first_name', 'student__last_name')
    ordering = ('-marked_at',)


@admin.register(TeacherAttendance)
class TeacherAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'session', 'status', 'self_reported', 'approved_by')
    list_filter = ('status',)
    search_fields = ('teacher__username',)
