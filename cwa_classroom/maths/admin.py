from django.contrib import admin
from .models import BasicFactsResult, TimeLog, Question, Answer


@admin.register(BasicFactsResult)
class BasicFactsResultAdmin(admin.ModelAdmin):
    list_display = ("student", "level", "points", "score", "total_points", "time_taken_seconds", "completed_at")
    list_filter = ("level", "completed_at")
    search_fields = ("student__username", "level__level_number")
    readonly_fields = ("completed_at",)
    ordering = ("-completed_at",)


@admin.register(TimeLog)
class TimeLogAdmin(admin.ModelAdmin):
    list_display = ("student", "daily_total_seconds", "weekly_total_seconds", "last_reset_date", "last_activity")
    list_filter = ("last_reset_date", "last_activity")
    search_fields = ("student__username",)
    readonly_fields = ("last_reset_date", "last_activity")


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 1


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("question_text", "level", "topic", "question_type", "validation_type", "difficulty", "points")
    list_filter = ("level", "topic", "question_type", "validation_type", "difficulty")
    search_fields = ("question_text", "grading_rubric")
    inlines = [AnswerInline]
    fieldsets = (
        (None, {
            'fields': ('question_text', 'level', 'topic', 'department', 'school',
                       'question_type', 'validation_type', 'difficulty', 'points'),
        }),
        ('Grading', {
            'fields': ('grading_rubric', 'explanation'),
            'description': (
                'grading_rubric: For ai_graded / human_graded questions — list KEY FACTS and '
                'THEOREMS a correct answer must use. List MULTIPLE valid proof paths. '
                'Do NOT prescribe one specific route.'
            ),
        }),
        ('Image', {
            'fields': ('image',),
            'classes': ('collapse',),
        }),
    )


