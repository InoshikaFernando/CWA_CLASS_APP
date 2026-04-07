from django.contrib import admin
from .models import (
    CodingLanguage,
    CodingTopic,
    CodingExercise,
    CodingProblem,
    ProblemTestCase,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    CodingTimeLog,
    CodingTopicStatistics,
)


@admin.register(CodingLanguage)
class CodingLanguageAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    ordering      = ('order',)


class CodingExerciseInline(admin.TabularInline):
    model  = CodingExercise
    extra  = 1
    fields = ('title', 'level', 'order', 'is_active')
    ordering = ('level', 'order')


@admin.register(CodingTopic)
class CodingTopicAdmin(admin.ModelAdmin):
    list_display  = ('name', 'language', 'order', 'is_active')
    list_filter   = ('language',)
    list_editable = ('order', 'is_active')
    ordering      = ('language', 'order')
    inlines       = [CodingExerciseInline]


@admin.register(CodingExercise)
class CodingExerciseAdmin(admin.ModelAdmin):
    list_display  = ('title', 'topic', 'level', 'order', 'is_active')
    list_filter   = ('topic__language', 'level', 'is_active')
    list_editable = ('order', 'is_active')
    search_fields = ('title', 'description')
    ordering      = ('topic', 'level', 'order')


class ProblemTestCaseInline(admin.TabularInline):
    model   = ProblemTestCase
    extra   = 2
    fields  = ('order', 'description', 'input_data', 'expected_output', 'is_visible')
    ordering = ('order',)


@admin.register(CodingProblem)
class CodingProblemAdmin(admin.ModelAdmin):
    list_display  = ('title', 'language', 'difficulty', 'is_active')
    list_filter   = ('language', 'difficulty', 'is_active')
    list_editable = ('difficulty', 'is_active')
    search_fields = ('title', 'description')
    ordering      = ('language', 'difficulty')
    inlines       = [ProblemTestCaseInline]


@admin.register(ProblemTestCase)
class ProblemTestCaseAdmin(admin.ModelAdmin):
    list_display = ('problem', 'order', 'description', 'is_visible')
    list_filter  = ('is_visible', 'problem__language')
    ordering     = ('problem', 'order')


@admin.register(StudentExerciseSubmission)
class StudentExerciseSubmissionAdmin(admin.ModelAdmin):
    list_display  = ('student', 'exercise', 'is_completed', 'submitted_at')
    list_filter   = ('is_completed', 'exercise__topic__language')
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