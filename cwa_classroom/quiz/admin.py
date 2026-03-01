from django.contrib import admin
from .models import Question, Answer


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 2
    fields = ('text', 'is_correct', 'display_order')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'topic', 'level', 'question_type', 'difficulty', 'points', 'created_at')
    list_filter = ('topic', 'level', 'question_type', 'difficulty')
    search_fields = ('question_text',)
    inlines = [AnswerInline]
    raw_id_fields = ('created_by',)


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ('text', 'question', 'is_correct', 'display_order')
    list_filter = ('is_correct',)
