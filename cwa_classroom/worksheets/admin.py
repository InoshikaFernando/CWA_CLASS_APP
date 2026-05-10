from django.contrib import admin

from .models import (
    Worksheet, WorksheetQuestion, WorksheetUploadSession,
    WorksheetAssignment, WorksheetSubmission, WorksheetStudentAnswer,
)


class WorksheetQuestionInline(admin.TabularInline):
    model = WorksheetQuestion
    extra = 0
    readonly_fields = ('order', 'question')


@admin.register(Worksheet)
class WorksheetAdmin(admin.ModelAdmin):
    list_display = ('name', 'school', 'question_count', 'created_by', 'created_at')
    list_filter = ('school',)
    search_fields = ('name', 'original_filename')
    inlines = [WorksheetQuestionInline]
    readonly_fields = ('question_count', 'created_at', 'updated_at')


@admin.register(WorksheetUploadSession)
class WorksheetUploadSessionAdmin(admin.ModelAdmin):
    list_display = ('pdf_filename', 'worksheet_name', 'user', 'school', 'is_confirmed', 'created_at')
    list_filter = ('is_confirmed', 'school')
    readonly_fields = ('created_at',)


class WorksheetSubmissionInline(admin.TabularInline):
    model = WorksheetSubmission
    extra = 0
    readonly_fields = ('student', 'started_at', 'completed_at', 'score', 'total_questions')


@admin.register(WorksheetAssignment)
class WorksheetAssignmentAdmin(admin.ModelAdmin):
    list_display = ('worksheet', 'classroom', 'question_start', 'question_end', 'is_active', 'assigned_at')
    list_filter = ('is_active', 'classroom__school')
    inlines = [WorksheetSubmissionInline]


@admin.register(WorksheetSubmission)
class WorksheetSubmissionAdmin(admin.ModelAdmin):
    list_display = ('student', 'assignment', 'score', 'total_questions', 'completed_at')
    list_filter = ('assignment__worksheet',)


@admin.register(WorksheetStudentAnswer)
class WorksheetStudentAnswerAdmin(admin.ModelAdmin):
    list_display = ('submission', 'question', 'is_correct', 'points_earned', 'answered_at')
    list_filter = ('is_correct',)
