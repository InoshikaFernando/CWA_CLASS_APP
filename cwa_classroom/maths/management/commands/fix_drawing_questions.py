"""
Re-grade bank questions whose answer is a DRAWING the app cannot accept.

"Draw a tree diagram to illustrate this situation." "Illustrate on a Venn
diagram the sets A = {1, 3, 5} and B = {2, 4, 6}." A student has no way to draw
anything in this app, so a question like that marked ``ai_graded`` hands them a
text box and marks them wrong however well they drew it on paper.

Uploads are handled at their source — ``worksheets.services`` routes these to
``human_graded`` at classification time, and the upload preview sweeps sessions
that predate that. This command is for the questions already in the bank, which
neither of those reaches.

Dry-run by DEFAULT: it prints what it would change and exits non-zero if
anything is pending, so a scheduled task can detect drift (same contract as
audit_mc_equivalent_options). Pass --apply to write.

Questions the app CAN take a drawing for are never touched — number lines,
Cartesian plots, draw-on-grid, shape-select, tables of values and the rest of
the structured types all render their own answer surface.

Usage:
    python manage.py fix_drawing_questions                    # dry run, whole bank
    python manage.py fix_drawing_questions --apply            # write the changes
    python manage.py fix_drawing_questions --topic 75         # one topic
    python manage.py fix_drawing_questions --level 7          # one year
    python manage.py fix_drawing_questions --school 3         # one school's questions
    python manage.py fix_drawing_questions --apply --quiet    # summary only
"""
import sys

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

# Single source of truth for "is this answer a drawing?" — the same predicate
# the upload path uses, so the bank and new imports can never disagree.
from worksheets.services import is_unanswerable_construction

RUBRIC_FALLBACK = (
    'The student has to draw this answer on paper — the app cannot take a '
    'drawing, so mark their working by hand.'
)


class Command(BaseCommand):
    help = (
        'Set bank questions whose answer is a drawing to human_graded so a '
        'teacher marks them instead of the AI grader.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command only reports.',
        )
        parser.add_argument(
            '--topic', type=int, default=None,
            help='Restrict to a single Topic id.',
        )
        parser.add_argument(
            '--level', type=int, default=None,
            help='Restrict to a single Level.level_number (year).',
        )
        parser.add_argument(
            '--school', type=int, default=None,
            help='Restrict to a single School id (omit for every question).',
        )
        parser.add_argument(
            '--quiet', action='store_true',
            help='Suppress per-question output; print only the summary.',
        )

    def handle(self, *args, **options):
        from maths.models import Question

        apply_changes = options['apply']
        quiet = options['quiet']

        # Only questions a grader would currently take. human_graded ones are
        # already where this command would put them, and re-reading them would
        # overwrite a rubric a teacher wrote.
        questions = (
            Question.objects
            .exclude(validation_type=Question.VALIDATION_HUMAN)
            .select_related('topic', 'level')
            # The predicate only measures how many options a question has, so
            # count them in the same query rather than fetching every answer row
            # for every question in the bank.
            .annotate(answer_count=Count('answers'))
        )
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])
        if options['school'] is not None:
            questions = questions.filter(school_id=options['school'])

        scanned = 0
        affected = []

        for question in questions.order_by('id').iterator():
            scanned += 1
            # is_unanswerable_construction reads the dict shape the extractor
            # produces; the two fields it looks at map straight across.
            if not is_unanswerable_construction({
                'question_text': question.question_text,
                'question_type': question.question_type,
                'answers': [None] * question.answer_count,
            }):
                continue
            affected.append(question)

            if quiet:
                continue
            topic = question.topic.name if question.topic_id else '(no topic)'
            year = question.level.level_number if question.level_id else '?'
            self.stdout.write(
                f'  Q{question.id} [year {year} / {topic}] '
                f'{question.validation_type} -> human_graded: '
                f'{question.question_text[:70]}'
            )

        if affected and apply_changes:
            with transaction.atomic():
                for question in affected:
                    question.validation_type = Question.VALIDATION_HUMAN
                    if not (question.grading_rubric or '').strip():
                        question.grading_rubric = RUBRIC_FALLBACK
                Question.objects.bulk_update(
                    affected, ['validation_type', 'grading_rubric'], batch_size=200,
                )

        msg = (
            f'Scanned {scanned} question(s) — {len(affected)} ask for a drawing '
            f'the app cannot accept'
        )
        if not affected:
            self.stdout.write(self.style.SUCCESS(msg))
            return

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(
                f'{msg}; all {len(affected)} set to human_graded. '
                'They are now hidden from quizzes and wait for a teacher.'
            ))
            return

        # Dry run with work outstanding: say so and fail, so a scheduled run
        # surfaces the drift rather than reporting a clean bank.
        self.stdout.write(self.style.ERROR(
            f'{msg}. Nothing was written — re-run with --apply to fix them.'
        ))
        sys.exit(1)
