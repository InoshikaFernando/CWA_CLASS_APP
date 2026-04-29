from django.contrib import admin
from django.utils.html import format_html
from .models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzAnswer,
)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class BrainBuzzSessionQuestionInline(admin.TabularInline):
    """Inline questions within session admin."""
    model = BrainBuzzSessionQuestion
    extra = 0
    readonly_fields = ('session', 'order')
    fields = ('order', 'question_type', 'question_text')
    can_delete = False


class BrainBuzzParticipantInline(admin.TabularInline):
    """Inline participants within session admin."""
    model = BrainBuzzParticipant
    extra = 0
    readonly_fields = ('joined_at', 'score')
    fields = ('nickname', 'student', 'score', 'joined_at')
    can_delete = False


# ---------------------------------------------------------------------------
# BrainBuzzSession Admin
# ---------------------------------------------------------------------------

@admin.register(BrainBuzzSession)
class BrainBuzzSessionAdmin(admin.ModelAdmin):
    """Admin for live quiz sessions."""
    
    list_display = (
        'code',
        'host',
        'subject',
        'status',
        'current_index',
        'state_version',
        'created_at',
        'started_at',
        'ended_at',
    )
    list_filter = ('status', 'subject', 'created_at')
    search_fields = ('code', 'host__username', 'subject__name')
    readonly_fields = (
        'code',
        'state_version',
        'created_at',
    )
    fieldsets = (
        ('Session Info', {
            'fields': ('code', 'host', 'subject'),
        }),
        ('State', {
            'fields': ('status', 'current_index', 'state_version', 'question_deadline'),
        }),
        ('Timing', {
            'fields': ('time_per_question_sec', 'created_at', 'started_at', 'ended_at'),
        }),
    )
    inlines = [BrainBuzzSessionQuestionInline, BrainBuzzParticipantInline]
    date_hierarchy = 'created_at'


# ---------------------------------------------------------------------------
# BrainBuzzSessionQuestion Admin
# ---------------------------------------------------------------------------

@admin.register(BrainBuzzSessionQuestion)
class BrainBuzzSessionQuestionAdmin(admin.ModelAdmin):
    """Admin for session questions (read-mostly, snapshots)."""
    
    list_display = (
        'code_link',
        'order',
        'question_type',
        'points_base',
        'source_model',
    )
    list_filter = ('question_type', 'source_model', 'session__created_at')
    search_fields = ('session__code', 'question_text')
    readonly_fields = (
        'session',
        'order',
        'source_model',
        'source_id',
        'options_json',
        'correct_short_answer',
    )
    fields = (
        'session',
        'order',
        'question_type',
        'question_text',
        'explanation',
        'points_base',
        'options_json',
        'correct_short_answer',
        'source_model',
        'source_id',
    )
    
    def code_link(self, obj):
        """Link to session."""
        return format_html(
            '<a href="/admin/brainbuzz/brainbuzzsession/{}/change/">{}</a>',
            obj.session.id,
            obj.session.code,
        )
    code_link.short_description = 'Session'
    
    def has_add_permission(self, request):
        """Questions should only be created via session lifecycle."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Protect question snapshots."""
        return False


# ---------------------------------------------------------------------------
# BrainBuzzParticipant Admin
# ---------------------------------------------------------------------------

@admin.register(BrainBuzzParticipant)
class BrainBuzzParticipantAdmin(admin.ModelAdmin):
    """Admin for session participants."""
    
    list_display = (
        'code_link',
        'nickname',
        'student',
        'score',
        'joined_at',
    )
    list_filter = ('session__created_at', 'joined_at')
    search_fields = ('nickname', 'session__code', 'student__username')
    readonly_fields = ('joined_at', 'session')
    fields = ('session', 'nickname', 'student', 'score', 'joined_at')
    
    def code_link(self, obj):
        """Link to session."""
        return format_html(
            '<a href="/admin/brainbuzz/brainbuzzsession/{}/change/">{}</a>',
            obj.session.id,
            obj.session.code,
        )
    code_link.short_description = 'Session'
    
    def has_add_permission(self, request):
        """Participants join via app, not admin."""
        return False


# ---------------------------------------------------------------------------
# BrainBuzzAnswer Admin
# ---------------------------------------------------------------------------

@admin.register(BrainBuzzAnswer)
class BrainBuzzAnswerAdmin(admin.ModelAdmin):
    """Admin for participant answers (read-mostly, high-volume data)."""
    
    list_display = (
        'participant_link',
        'question_link',
        'correct_indicator',
        'points_awarded',
        'time_taken_ms',
        'submitted_at',
    )
    list_filter = (
        'is_correct',
        'session_question__question_type',
        'submitted_at',
    )
    search_fields = (
        'participant__nickname',
        'participant__session__code',
        'session_question__question_text',
    )
    readonly_fields = (
        'participant',
        'session_question',
        'selected_option_label',
        'short_answer_text',
        'submitted_at',
    )
    fields = (
        'participant',
        'session_question',
        'selected_option_label',
        'short_answer_text',
        'submitted_at',
        'time_taken_ms',
        'points_awarded',
        'is_correct',
    )
    
    def get_queryset(self, request):
        """Use select_related to avoid N+1 queries."""
        qs = super().get_queryset(request)
        return qs.select_related(
            'participant',
            'participant__session',
            'session_question',
            'session_question__session',
        )
    
    def participant_link(self, obj):
        """Link to participant."""
        return format_html(
            '<a href="/admin/brainbuzz/brainbuzzparticipant/{}/change/">{}</a>',
            obj.participant.id,
            obj.participant.nickname,
        )
    participant_link.short_description = 'Participant'
    
    def question_link(self, obj):
        """Link to session question."""
        return format_html(
            'Q{} in <a href="/admin/brainbuzz/brainbuzzsession/{}/change/">{}</a>',
            obj.session_question.order,
            obj.session_question.session.id,
            obj.session_question.session.code,
        )
    question_link.short_description = 'Question'
    
    def correct_indicator(self, obj):
        """Visual indicator of correctness."""
        if obj.is_correct:
            return format_html('<span style="color: green;">✓ Correct</span>')
        return format_html('<span style="color: red;">✗ Wrong</span>')
    correct_indicator.short_description = 'Result'
    
    def has_add_permission(self, request):
        """Answers are created by app, not admin."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Protect answer data for auditing."""
        return False
    readonly_fields = ('submitted_at',)
