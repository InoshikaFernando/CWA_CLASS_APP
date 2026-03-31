from django.contrib import admin

from .models import Homework, HomeworkSubmission


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'classroom', 'topic', 'status', 'due_date',
        'assigned_by', 'is_active', 'created_at',
    ]
    list_filter = ['status', 'is_active', 'classroom__school', 'due_date']
    search_fields = ['title', 'classroom__name', 'topic__name']
    raw_id_fields = ['classroom', 'topic', 'assigned_by']
    date_hierarchy = 'due_date'
    readonly_fields = ['assigned_date', 'published_at', 'created_at', 'updated_at']


@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = [
        'homework', 'student', 'attempt_number', 'is_late',
        'is_graded', 'is_published', 'score', 'submitted_at',
    ]
    list_filter = ['is_late', 'is_graded', 'is_published']
    search_fields = ['homework__title', 'student__username', 'student__first_name']
    raw_id_fields = ['homework', 'student', 'graded_by']
    readonly_fields = ['submitted_at']
