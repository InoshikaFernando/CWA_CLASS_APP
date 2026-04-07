from django.contrib import admin
from .models import (
    CodingLanguage,
    CodingTopic,
    TopicLevel,
    CodingExercise,
    CodingProblem,
    ProblemTestCase,
    StudentExerciseAttempt,
    StudentProblemSubmission,
    ProblemSubmissionResult,
    CodingTimeLog,
    CodingTopicStatistics,
)


@admin.register(CodingLanguage)
class CodingLanguageAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'display_order', 'is_active')
    list_editable = ('display_order', 'is_active')
    ordering      = ('display_order',)


class CodingExerciseInline(admin.TabularInline):
    model  = CodingExercise
    extra  = 1
    fields = ('title', 'display_order', 'is_active')
    ordering = ('display_order',)


@admin.register(CodingTopic)
class CodingTopicAdmin(admin.ModelAdmin):
    list_display  = ('name', 'language', 'display_order', 'is_active')
    list_filter   = ('language',)
    list_editable = ('display_order', 'is_active')
    ordering      = ('language', 'display_order')


@admin.register(TopicLevel)
class TopicLevelAdmin(admin.ModelAdmin):
    list_display  = ('topic', 'level_choice')
    list_filter   = ('level_choice', 'topic__language')
    ordering      = ('topic', 'level_choice')
    inlines       = [CodingExerciseInline]


@admin.register(CodingExercise)
class CodingExerciseAdmin(admin.ModelAdmin):
    list_display  = ('title', 'topic_level', 'display_order', 'is_active')
    list_filter   = ('topic_level__topic__language', 'topic_level__level_choice', 'is_active')
    list_editable = ('display_order', 'is_active')
    search_fields = ('title', 'instructions')
    ordering      = ('topic_level', 'display_order')


class ProblemTestCaseInline(admin.TabularInline):
    model   = ProblemTestCase
    extra   = 2
    fields  = ('order', 'description', 'input_data', 'expected_output', 'is_visible', 'is_boundary_test')
    ordering = ('order',)


@admin.register(CodingProblem)
class CodingProblemAdmin(admin.ModelAdmin):
    list_display  = ('title', 'language', 'category', 'difficulty', 'time_limit_seconds', 'memory_limit_mb', 'is_active')
    list_filter   = ('language', 'category', 'difficulty', 'is_active')
    list_editable = ('category', 'difficulty', 'is_active')
    search_fields = ('title', 'description')
    ordering      = ('language', 'difficulty')
    fieldsets = (
        (None, {
            'fields': ('language', 'title', 'description', 'category', 'difficulty', 'is_active'),
        }),
        ('Constraints & Limits', {
            'fields': ('constraints', 'time_limit_seconds', 'memory_limit_mb'),
        }),
        ('Code', {
            'fields': ('starter_code', 'solution_code'),
            'classes': ('collapse',),
        }),
    )
    inlines = [ProblemTestCaseInline]


@admin.register(ProblemTestCase)
class ProblemTestCaseAdmin(admin.ModelAdmin):
    list_display = ('problem', 'order', 'description', 'is_visible', 'is_boundary_test')
    list_filter  = ('is_visible', 'is_boundary_test', 'problem__language')
    ordering     = ('problem', 'order')


@admin.register(StudentExerciseAttempt)
class StudentExerciseAttemptAdmin(admin.ModelAdmin):
    list_display  = ('student', 'exercise', 'is_correct', 'attempted_at')
    list_filter   = ('is_correct', 'exercise__topic_level__topic__language')
    search_fields = ('student__username',)
    ordering      = ('-attempted_at',)
    readonly_fields = ('attempted_at',)


class ProblemSubmissionResultInline(admin.TabularInline):
    model         = ProblemSubmissionResult
    extra         = 0
    fields        = ('test_case', 'is_passed', 'actual_output', 'execution_time_ms')
    readonly_fields = ('test_case', 'actual_output', 'execution_time_ms')
    can_delete    = False


@admin.register(StudentProblemSubmission)
class StudentProblemSubmissionAdmin(admin.ModelAdmin):
    list_display  = ('student', 'problem', 'language', 'attempt_number', 'status', 'passed_all_tests', 'points', 'submitted_at')
    list_filter   = ('status', 'passed_all_tests', 'problem__language', 'language')
    search_fields = ('student__username', 'problem__title')
    ordering      = ('-submitted_at',)
    readonly_fields = ('submitted_at', 'test_results')
    inlines       = [ProblemSubmissionResultInline]


@admin.register(ProblemSubmissionResult)
class ProblemSubmissionResultAdmin(admin.ModelAdmin):
    list_display  = ('submission', 'test_case', 'is_passed', 'execution_time_ms')
    list_filter   = ('is_passed',)
    ordering      = ('submission', 'test_case__order')
    readonly_fields = ('submission', 'test_case', 'actual_output', 'execution_time_ms')


@admin.register(CodingTimeLog)
class CodingTimeLogAdmin(admin.ModelAdmin):
    list_display = ('student', 'daily_total_seconds', 'weekly_total_seconds', 'last_activity')
    search_fields = ('student__username',)
    ordering      = ('-last_activity',)


@admin.register(CodingTopicStatistics)
class CodingTopicStatisticsAdmin(admin.ModelAdmin):
    list_display = ('topic', 'level', 'average_points', 'sigma', 'student_count', 'last_updated')
    list_filter  = ('level', 'topic__language')
    ordering     = ('topic', 'level')