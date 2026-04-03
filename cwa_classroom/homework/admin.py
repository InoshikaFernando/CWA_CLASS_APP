from django.contrib import admin

from .models import Homework, HomeworkQuestion, HomeworkSubmission


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'homework_type', 'classroom', 'topic', 'status', 'due_date',
        'assigned_by', 'is_active', 'created_at',
    ]
    list_filter = ['homework_type', 'status', 'is_active', 'classroom__school', 'due_date']
    search_fields = ['title', 'classroom__name', 'topic__name']
    raw_id_fields = ['classroom', 'topic', 'assigned_by', 'quiz_level']
    date_hierarchy = 'due_date'
    readonly_fields = ['assigned_date', 'published_at', 'created_at', 'updated_at']
    filter_horizontal = ['quiz_topics']


@admin.register(HomeworkQuestion)
class HomeworkQuestionAdmin(admin.ModelAdmin):
    list_display = ['homework', 'question', 'order']
    list_filter = ['homework']
    raw_id_fields = ['homework', 'question']


@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = [
        'homework', 'student', 'attempt_number', 'is_late',
        'is_auto_completed', 'is_graded', 'is_published', 'score', 'submitted_at',
    ]
    list_filter = ['is_late', 'is_graded', 'is_published', 'is_auto_completed']
    search_fields = ['homework__title', 'student__username', 'student__first_name']
    raw_id_fields = ['homework', 'student', 'graded_by', 'quiz_result']
    readonly_fields = ['submitted_at']
