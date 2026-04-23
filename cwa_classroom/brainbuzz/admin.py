from django.contrib import admin
from .models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzSubmission,
)


class BrainBuzzSessionQuestionInline(admin.TabularInline):
    model = BrainBuzzSessionQuestion
    extra = 0
    readonly_fields = ('question_start_time_utc', 'question_deadline_utc')


class BrainBuzzParticipantInline(admin.TabularInline):
    model = BrainBuzzParticipant
    extra = 0
    readonly_fields = ('joined_at', 'total_score')


@admin.register(BrainBuzzSession)
class BrainBuzzSessionAdmin(admin.ModelAdmin):
    list_display = ('join_code', 'created_by', 'subject', 'state', 'state_version', 'created_at')
    list_filter = ('state', 'subject')
    search_fields = ('join_code', 'created_by__username')
    readonly_fields = ('join_code', 'state_version', 'created_at', 'updated_at')
    inlines = [BrainBuzzSessionQuestionInline, BrainBuzzParticipantInline]


@admin.register(BrainBuzzSessionQuestion)
class BrainBuzzSessionQuestionAdmin(admin.ModelAdmin):
    list_display = ('session', 'order_index', 'question_type', 'time_limit_seconds')
    list_filter = ('question_type',)
    search_fields = ('session__join_code', 'question_text')
    readonly_fields = ('question_start_time_utc', 'question_deadline_utc')


@admin.register(BrainBuzzParticipant)
class BrainBuzzParticipantAdmin(admin.ModelAdmin):
    list_display = ('session', 'nickname', 'user', 'total_score', 'is_active', 'joined_at')
    list_filter = ('is_active',)
    search_fields = ('nickname', 'session__join_code', 'user__username')
    readonly_fields = ('joined_at',)


@admin.register(BrainBuzzSubmission)
class BrainBuzzSubmissionAdmin(admin.ModelAdmin):
    list_display = ('participant', 'session_question', 'is_correct', 'score_awarded', 'submitted_at')
    list_filter = ('is_correct',)
    readonly_fields = ('submitted_at',)
