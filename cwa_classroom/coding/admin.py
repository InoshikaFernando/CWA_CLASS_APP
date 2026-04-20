from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CodingLanguage,
    CodingTopic,
    TopicLevel,
    CodingExercise,
    CodingProblem,
    ProblemTestCase,
    ProblemSubmission,
    ProblemSubmissionResult,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    CodingTimeLog,
    CodingTopicStatistics,
)


# ---------------------------------------------------------------------------
# Language & Topic
# ---------------------------------------------------------------------------

@admin.register(CodingLanguage)
class CodingLanguageAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    ordering      = ('order',)


class CodingExerciseInline(admin.TabularInline):
    model    = CodingExercise
    extra    = 1
    fields   = ('title', 'order', 'is_active')
    ordering = ('order',)


@admin.register(TopicLevel)
class TopicLevelAdmin(admin.ModelAdmin):
    list_display  = ('topic', 'level_choice', 'is_active', 'order')
    list_filter   = ('topic__language', 'level_choice', 'is_active')
    list_editable = ('is_active', 'order')
    ordering      = ('topic', 'level_choice')
    inlines       = [CodingExerciseInline]


@admin.register(CodingTopic)
class CodingTopicAdmin(admin.ModelAdmin):
    list_display  = ('name', 'language', 'order', 'is_active')
    list_filter   = ('language',)
    list_editable = ('order', 'is_active')
    ordering      = ('language', 'order')


@admin.register(CodingExercise)
class CodingExerciseAdmin(admin.ModelAdmin):
    list_display  = ('title', 'topic_level', 'order', 'is_active')
    list_filter   = ('topic_level__topic__language', 'topic_level__level_choice', 'is_active')
    list_editable = ('order', 'is_active')
    search_fields = ('title', 'description')
    ordering      = ('topic_level__topic', 'topic_level__level_choice', 'order')


# ---------------------------------------------------------------------------
# Problem Solving — CodingProblem + ProblemTestCase
# ---------------------------------------------------------------------------

class ProblemTestCaseInline(admin.TabularInline):
    model   = ProblemTestCase
    extra   = 2
    fields  = ('display_order', 'description', 'input_data', 'expected_output',
               'is_visible', 'is_boundary_test')
    ordering = ('display_order',)


@admin.register(CodingProblem)
class CodingProblemAdmin(admin.ModelAdmin):
    list_display  = (
        'title', 'category', 'difficulty', 'language',
        'time_limit_seconds', 'memory_limit_mb',
        'visible_count', 'hidden_count', 'is_active',
    )
    list_filter   = ('category', 'difficulty', 'language', 'is_active')
    list_editable = ('difficulty', 'is_active')
    search_fields = ('title', 'description')
    ordering      = ('difficulty', 'title')
    inlines       = [ProblemTestCaseInline]
    fieldsets = (
        (None, {
            'fields': ('title', 'category', 'difficulty', 'is_active', 'language'),
        }),
        ('Problem Statement', {
            'fields': ('description', 'constraints'),
        }),
        ('Limits', {
            'fields': ('time_limit_seconds', 'memory_limit_mb'),
        }),
        ('Code', {
            'classes': ('collapse',),
            'fields': ('starter_code', 'solution_code'),
        }),
    )

    @admin.display(description='Visible tests')
    def visible_count(self, obj):
        n = obj.test_cases.filter(is_visible=True).count()
        colour = 'green' if n >= 2 else 'red'
        return format_html('<span style="color:{}">{}</span>', colour, n)

    @admin.display(description='Hidden tests')
    def hidden_count(self, obj):
        return obj.test_cases.filter(is_visible=False).count()


@admin.register(ProblemTestCase)
class ProblemTestCaseAdmin(admin.ModelAdmin):
    list_display = ('problem', 'display_order', 'description', 'is_visible', 'is_boundary_test')
    list_filter  = ('is_visible', 'is_boundary_test', 'problem__category')
    list_editable = ('is_visible', 'is_boundary_test')
    search_fields = ('problem__title', 'description')
    ordering     = ('problem', 'display_order')


# ---------------------------------------------------------------------------
# Problem Solving — ProblemSubmission + ProblemSubmissionResult
# ---------------------------------------------------------------------------

class ProblemSubmissionResultInline(admin.TabularInline):
    model         = ProblemSubmissionResult
    extra         = 0
    can_delete    = False
    readonly_fields = ('test_case', 'is_passed', 'execution_time_ms', 'actual_output')
    fields        = ('test_case', 'is_passed', 'execution_time_ms', 'actual_output')
    ordering      = ('test_case__display_order',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ProblemSubmission)
class ProblemSubmissionAdmin(admin.ModelAdmin):
    list_display  = (
        'student', 'problem', 'language', 'status_badge',
        'test_cases_passed', 'total_test_cases', 'pass_rate_display',
        'submitted_at',
    )
    list_filter   = ('status', 'language', 'problem__category', 'problem__difficulty')
    search_fields = ('student__username', 'problem__title')
    ordering      = ('-submitted_at',)
    readonly_fields = ('submitted_at',)
    inlines       = [ProblemSubmissionResultInline]
    date_hierarchy = 'submitted_at'

    @admin.display(description='Status', ordering='status')
    def status_badge(self, obj):
        colours = {
            ProblemSubmission.PENDING: ('#d97706', 'Pending'),
            ProblemSubmission.PASSED:  ('#16a34a', 'Passed'),
            ProblemSubmission.FAILED:  ('#dc2626', 'Failed'),
        }
        colour, label = colours.get(obj.status, ('#6b7280', obj.status))
        return format_html(
            '<span style="color:{}; font-weight:600">{}</span>', colour, label,
        )

    @admin.display(description='Pass rate')
    def pass_rate_display(self, obj):
        return f'{obj.pass_rate}%'


@admin.register(ProblemSubmissionResult)
class ProblemSubmissionResultAdmin(admin.ModelAdmin):
    list_display  = ('submission', 'test_case', 'is_passed', 'execution_time_ms')
    list_filter   = ('is_passed', 'test_case__is_boundary_test')
    search_fields = ('submission__student__username', 'submission__problem__title')
    ordering      = ('submission', 'test_case__display_order')
    readonly_fields = ('submission', 'test_case', 'actual_output', 'is_passed', 'execution_time_ms')

    def has_add_permission(self, request):
        return False


# ---------------------------------------------------------------------------
# Student Exercise & Problem history (legacy / monitoring)
# ---------------------------------------------------------------------------

@admin.register(StudentExerciseSubmission)
class StudentExerciseSubmissionAdmin(admin.ModelAdmin):
    list_display  = ('student', 'exercise', 'is_completed', 'submitted_at')
    list_filter   = ('is_completed', 'exercise__topic_level__topic__language')
    search_fields = ('student__username',)
    ordering      = ('-submitted_at',)
    readonly_fields = ('submitted_at',)


@admin.register(StudentProblemSubmission)
class StudentProblemSubmissionAdmin(admin.ModelAdmin):
    list_display  = ('student', 'problem', 'attempt_number', 'passed_all_tests', 'points', 'submitted_at')
    list_filter   = ('passed_all_tests', 'problem__language')
    search_fields = ('student__username', 'problem__title')
    ordering      = ('-submitted_at',)
    readonly_fields = ('submitted_at', 'test_results')


# ---------------------------------------------------------------------------
# Time tracking & Statistics
# ---------------------------------------------------------------------------

@admin.register(CodingTimeLog)
class CodingTimeLogAdmin(admin.ModelAdmin):
    list_display  = ('student', 'daily_total_seconds', 'weekly_total_seconds', 'last_activity')
    search_fields = ('student__username',)
    ordering      = ('-last_activity',)


@admin.register(CodingTopicStatistics)
class CodingTopicStatisticsAdmin(admin.ModelAdmin):
    list_display = ('topic', 'level', 'average_points', 'sigma', 'student_count', 'last_updated')
    list_filter  = ('level', 'topic__language')
    ordering     = ('topic', 'level')
