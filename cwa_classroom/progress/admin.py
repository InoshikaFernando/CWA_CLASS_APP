from django.contrib import admin
from .models import StudentFinalAnswer, BasicFactsResult, TopicLevelStatistics, TimeLog


@admin.register(StudentFinalAnswer)
class StudentFinalAnswerAdmin(admin.ModelAdmin):
    list_display = ('student', 'topic', 'level', 'quiz_type', 'score', 'total_questions', 'points', 'completed_at')
    list_filter = ('quiz_type', 'level', 'topic')
    search_fields = ('student__username',)
    readonly_fields = ('completed_at', 'session_id')


@admin.register(BasicFactsResult)
class BasicFactsResultAdmin(admin.ModelAdmin):
    list_display = ('student', 'subtopic', 'level_number', 'score', 'total_questions', 'points', 'time_taken_seconds', 'completed_at')
    list_filter = ('subtopic',)
    search_fields = ('student__username',)
    readonly_fields = ('completed_at',)


@admin.register(TopicLevelStatistics)
class TopicLevelStatisticsAdmin(admin.ModelAdmin):
    list_display = ('topic', 'level', 'avg_points', 'sigma', 'student_count', 'updated_at')


@admin.register(TimeLog)
class TimeLogAdmin(admin.ModelAdmin):
    list_display = ('student', 'daily_seconds', 'weekly_seconds', 'last_updated')
    search_fields = ('student__username',)
