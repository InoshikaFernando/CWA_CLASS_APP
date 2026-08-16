"""
Audit multiple-choice questions for distractors that are mathematically EQUAL
to the correct answer.

A student who solves the problem correctly and picks the unsimplified form of
their own answer is marked wrong — the defect behind CPP-377, where 14 of the
57 questions on one Year 7 fractions topic offered options like '9/3 kg'
alongside the correct '3 kg'.

Read-only. Prints the offending rows and exits non-zero if any are found, so a
scheduled task / CI step can detect drift automatically (same contract as
audit_question_image_paths).

Usage:
    python manage.py audit_mc_equivalent_options                  # whole DB
    python manage.py audit_mc_equivalent_options --topic 75       # one topic
    python manage.py audit_mc_equivalent_options --level 7        # one year
    python manage.py audit_mc_equivalent_options --quiet          # summary only
"""
import sys

from django.core.management.base import BaseCommand

# Single source of truth for "what number is this answer text?".
from maths.answer_values import find_equivalent_options


class Command(BaseCommand):
    help = (
        'Audit multiple-choice questions for distractors numerically equal to '
        'the correct answer.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--topic', type=int, default=None,
            help='Restrict the audit to a single Topic id.',
        )
        parser.add_argument(
            '--level', type=int, default=None,
            help='Restrict the audit to a single Level.level_number (year).',
        )
        parser.add_argument(
            '--quiet', action='store_true',
            help='Suppress per-row output; print only the summary.',
        )

    def handle(self, *args, **options):
        from maths.models import Question

        quiet = options['quiet']

        questions = (
            Question.objects
            .filter(question_type__in=(Question.MULTIPLE_CHOICE, Question.TRUE_FALSE))
            .select_related('topic', 'level')
            .prefetch_related('answers')
        )
        if options['topic'] is not None:
            questions = questions.filter(topic_id=options['topic'])
        if options['level'] is not None:
            questions = questions.filter(level__level_number=options['level'])

        scanned = 0
        affected = []
        clash_count = 0

        for question in questions.order_by('id'):
            scanned += 1
            clashes = find_equivalent_options(question)
            if not clashes:
                continue
            affected.append(question)
            clash_count += len(clashes)

            if quiet:
                continue

            topic = question.topic.name if question.topic_id else '(no topic)'
            year = question.level.level_number if question.level_id else '?'
            self.stdout.write(
                f'  Q{question.id} [year {year} / {topic}] '
                f'{question.question_text[:70]}'
            )
            for distractor, correct in clashes:
                self.stdout.write(
                    f'      distractor A{distractor.id} '
                    f'{distractor.answer_text!r} == '
                    f'correct {correct.answer_text!r}'
                )

        msg = (
            f'Audited {scanned} choice question(s) — '
            f'{len(affected)} with equivalent distractors '
            f'({clash_count} bad option(s))'
        )
        if affected:
            self.stdout.write(self.style.ERROR(msg))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(msg))
