from django.contrib import admin, messages
from django.utils import timezone
from django.utils.safestring import mark_safe

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
    list_display = ("question_text", "level", "topic", "question_type", "validation_type",
                    "difficulty", "points", "retirement_status")
    list_filter = ("level", "topic", "question_type", "validation_type", "difficulty",
                   "retired_at")
    search_fields = ("question_text", "grading_rubric")
    inlines = [AnswerInline]
    readonly_fields = ("measure_figure_preview",)
    fieldsets = (
        (None, {
            'fields': ('question_text', 'level', 'topic', 'department', 'school',
                       'question_type', 'answer_format', 'validation_type', 'difficulty', 'points'),
        }),
        ('Grading', {
            'fields': ('grading_rubric', 'explanation'),
            'description': (
                'grading_rubric: For ai_graded / human_graded questions — list KEY FACTS and '
                'THEOREMS a correct answer must use. List MULTIPLE valid proof paths. '
                'Do NOT prescribe one specific route.'
            ),
        }),
        ('Measure', {
            'fields': ('numeric_answer', 'answer_tolerance', 'answer_unit', 'measure_figure_preview'),
            'classes': ('collapse',),
            'description': (
                'For "measure" questions: the true value the student must measure '
                '(numeric_answer), the accepted ± band (answer_tolerance — blank/0 = exact), '
                'and the unit shown in the box (e.g. °). The figure below is generated '
                'from the value — no image upload needed.'
            ),
        }),
        ('Image', {
            'fields': ('image',),
            'classes': ('collapse',),
        }),
        ('Retirement', {
            'fields': ('retired_at', 'retired_reason'),
            'classes': ('collapse',),
            'description': (
                'Set retired_at to withdraw this question from all future '
                'homework, worksheets and quizzes, and from the take page of '
                'homework that already contains it. Past submissions keep it, '
                'shown greyed with the answer the student gave — nothing is '
                'deleted and no mark changes. Clear it to bring the question '
                'back. Prefer this to deleting: deleting CASCADEs and would '
                'destroy every answer ever given to this question.'
            ),
        }),
    )

    # ---- Retirement (CPP-410) ------------------------------------------
    # Retiring is the supported way to take a broken question out of service.
    # Deleting is not: every FK to Question is on_delete=CASCADE, so it would
    # take every homework, worksheet and quiz answer ever given to it, and
    # rewrite completed homework to tidy up (say) a diagram that never got
    # attached. These actions are what make retirement reachable without a
    # shell — the model has had ``retire()`` since CPP-410, but a lever nobody
    # can pull is not a lever.
    actions = ['retire_questions', 'unretire_questions']

    @admin.display(description='Status', boolean=False)
    def retirement_status(self, obj):
        """Live or withdrawn, at a glance in the changelist."""
        if not obj.is_retired:
            return 'Live'
        reason = (obj.retired_reason or '').strip()
        when = obj.retired_at.date().isoformat() if obj.retired_at else ''
        return f'Withdrawn {when}' + (f' — {reason[:60]}' if reason else '')

    @admin.action(description='Retire — withdraw from all future selection')
    def retire_questions(self, request, queryset):
        """Withdraw the selected questions, keeping every answer to them.

        The reason is deliberately generic here: the admin's action bar has
        nowhere to type one, and inventing a specific reason on the reviewer's
        behalf would put words in the record. Anyone who wants a real reason
        uses ``manage.py retire_question --reason``, or edits the field.
        """
        already = queryset.filter(retired_at__isnull=False).count()
        live = queryset.filter(retired_at__isnull=True)
        count = live.count()
        live.update(
            retired_at=timezone.now(),
            retired_reason='Withdrawn from the Django admin.',
        )
        if count:
            self.message_user(
                request,
                f'{count} question(s) withdrawn. They will no longer be set, '
                f'including in homework that already contains them. Past '
                f'submissions keep them, shown greyed — no answer was deleted '
                f'and no mark changed.',
                messages.SUCCESS,
            )
        if already:
            # Say what was skipped rather than let the count read as the whole
            # story — the reviewer selected these rows expecting something.
            self.message_user(
                request, f'{already} were already withdrawn and were left as '
                         f'they are.', messages.INFO)

    @admin.action(description='Un-retire — put back into service')
    def unretire_questions(self, request, queryset):
        retired = queryset.filter(retired_at__isnull=False)
        count = retired.count()
        retired.update(retired_at=None, retired_reason='')
        self.message_user(
            request,
            f'{count} question(s) put back into service.'
            if count else 'None of the selected questions was withdrawn.',
            messages.SUCCESS if count else messages.INFO,
        )

    @admin.display(description='Generated figure preview')
    def measure_figure_preview(self, obj):
        """Render the generated angle figure so authors can sanity-check the value."""
        svg = obj.measure_figure_svg if obj else ''
        if not svg:
            return 'Set question_type=measure and a numeric answer to preview the figure.'
        return mark_safe(f'<div style="max-width:240px">{svg}</div>')


