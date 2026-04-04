from django.contrib import admin
from .models import Homework, HomeworkQuestion, HomeworkSubmission, HomeworkStudentAnswer


class HomeworkQuestionInline(admin.TabularInline):
    model = HomeworkQuestion
    extra = 0
    raw_id_fields = ('question',)


class HomeworkSubmissionInline(admin.TabularInline):
    model = HomeworkSubmission
    extra = 0
    readonly_fields = ('attempt_number', 'score', 'total_questions', 'points', 'submitted_at')
    can_delete = False


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ('title', 'classroom', 'created_by', 'due_date', 'max_attempts', 'created_at')
    list_filter = ('classroom', 'homework_type')
    search_fields = ('title', 'classroom__code')
    inlines = [HomeworkQuestionInline, HomeworkSubmissionInline]


@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = ('homework', 'student', 'attempt_number', 'score', 'total_questions', 'points', 'submitted_at')
    list_filter = ('homework__classroom',)
    search_fields = ('student__username', 'homework__title')
