from django.contrib import admin

from .models import (
    Language,
    LanguageAnswer,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'script_type', 'is_active', 'order')
    list_filter = ('script_type', 'is_active')
    search_fields = ('name', 'code')
    ordering = ('order', 'name')


@admin.register(LanguageTopic)
class LanguageTopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'language', 'order', 'is_active')
    list_filter = ('language', 'is_active')
    search_fields = ('name',)
    ordering = ('language', 'order', 'name')


@admin.register(LanguageTopicLevel)
class LanguageTopicLevelAdmin(admin.ModelAdmin):
    list_display = ('topic', 'level_choice')
    list_filter = ('level_choice', 'topic__language')
    search_fields = ('topic__name',)


class LanguageAnswerInline(admin.TabularInline):
    model = LanguageAnswer
    extra = 2
    fields = ('answer_text', 'is_correct', 'display_order')


@admin.register(LanguageExercise)
class LanguageExerciseAdmin(admin.ModelAdmin):
    list_display = ('prompt_short', 'exercise_type', 'topic_level', 'points', 'is_active', 'order')
    list_filter = ('exercise_type', 'is_active', 'topic_level__topic__language')
    search_fields = ('prompt',)
    ordering = ('topic_level', 'order')
    inlines = [LanguageAnswerInline]

    @admin.display(description='Prompt')
    def prompt_short(self, obj):
        return obj.prompt[:60]


@admin.register(LanguageAnswer)
class LanguageAnswerAdmin(admin.ModelAdmin):
    list_display = ('answer_text', 'exercise', 'is_correct', 'display_order')
    list_filter = ('is_correct',)
    search_fields = ('answer_text',)


@admin.register(LanguageStudentAnswer)
class LanguageStudentAnswerAdmin(admin.ModelAdmin):
    list_display = ('student', 'exercise', 'is_correct', 'points_earned', 'has_stroke', 'answered_at')
    list_filter = ('is_correct',)
    search_fields = ('student__username', 'student__email')
    readonly_fields = ('answered_at', 'stroke_data')
    raw_id_fields = ('student', 'exercise', 'selected_answer')

    @admin.display(boolean=True, description='Has drawing')
    def has_stroke(self, obj):
        return bool(obj.stroke_data and obj.stroke_data.get('objects'))
