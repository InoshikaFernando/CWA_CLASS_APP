"""
set_pattern_answer_format
~~~~~~~~~~~~~~~~~~~~~~~~~
Flag "create your own number pattern" questions as pattern-graded
(answer_format='pattern') so the grader checks the pattern the student invented
instead of comparing it to an answer that cannot exist.

Why this exists: these questions are authored with no correct Answer row —
there is no single right answer to "Create your own tricky subtraction number
pattern of six numbers" — and a typed answer with nothing to match against is
scored WRONG. Every student who has ever answered one has lost the mark, and
the quiz showed a bare "❌ Incorrect" with no answer beside it. Tagging the
question routes it to maths.pattern_grading, which grades the numbers against
what the question asked for (same step each time, right operation, right
count) and explains the mark.

Scope:
  - question_text asks the student to invent a pattern — the wording must
    contain "your own" (or "make up") AND "pattern"/"sequence", so
    "Write down the next three numbers in this pattern" is NOT matched
  - question_type is a typed one (choice questions ignore answer_format)
  - questions that DO have a stored correct answer are listed but skipped —
    tagging one would stop that answer being accepted. Use --include-answered
    if the stored "answer" turns out to be a worked example rather than the
    answer (which is how several of them were authored).

Usage (run from cwa_classroom/):
    python manage.py set_pattern_answer_format                  # dry run
    python manage.py set_pattern_answer_format --level 4
    python manage.py set_pattern_answer_format --topic 147
    python manage.py set_pattern_answer_format --apply          # actually write
"""
from django.core.management.base import BaseCommand

from maths.models import Question
from maths.pattern_grading import (
    example_answer, looks_like_pattern_question, parse_pattern_request,
)

TYPED_TYPES = ['short_answer', 'calculation', 'fill_blank', 'extended_answer']


class Command(BaseCommand):
    help = ("Set answer_format='pattern' on \"create your own number pattern\" "
            'questions, which have no stored answer and so mark every student wrong.')

    def add_arguments(self, parser):
        parser.add_argument('--level', type=int, default=None,
                            help='Limit to one year level (level_number).')
        parser.add_argument('--topic', type=int, default=None,
                            help='Limit to one topic id.')
        parser.add_argument(
            '--include-answered', action='store_true',
            help='Also tag questions that already have a stored correct answer. '
                 'Read the listed answers first — tagging stops them being matched.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command only reports (dry run).',
        )

    def handle(self, *args, **opts):
        qs = (
            Question.objects
            .filter(question_type__in=TYPED_TYPES)
            .exclude(answer_format=Question.ANSWER_FORMAT_PATTERN)
            .select_related('topic', 'level')
            .prefetch_related('answers')
            .order_by('id')
        )
        if opts['level'] is not None:
            qs = qs.filter(level__level_number=opts['level'])
        if opts['topic'] is not None:
            qs = qs.filter(topic_id=opts['topic'])

        matched, skipped = [], []
        for question in qs:
            if not looks_like_pattern_question(question.question_text):
                continue
            has_answer = any(
                (a.answer_text or '').strip()
                for a in question.answers.all() if a.is_correct
            )
            if has_answer and not opts['include_answered']:
                skipped.append(question)
            else:
                matched.append(question)

        for question in matched:
            request = parse_pattern_request(question.question_text)
            year = question.level.level_number if question.level_id else '?'
            topic = question.topic.name if question.topic_id else '(no topic)'
            self.stdout.write(f'  • Q{question.id} [year {year} / {topic}] '
                              f'{question.question_text[:70]}')
            self.stdout.write(f'      reads as {request} '
                              f'→ e.g. {example_answer(request)}')

        if skipped:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(skipped)} matching question(s) already have a stored '
                f'answer and were NOT tagged:'))
            for question in skipped:
                answers = ' | '.join(
                    a.answer_text for a in question.answers.all()
                    if a.is_correct and (a.answer_text or '').strip())
                self.stdout.write(f'  • Q{question.id} {question.question_text[:60]}')
                self.stdout.write(f'      stored answer: {answers[:100]}')
            self.stdout.write('  (re-run with --include-answered if those are '
                              'worked examples rather than the answer)')

        self.stdout.write('')
        self.stdout.write(f'Questions to tag as pattern-graded: {len(matched)}')

        if not matched:
            return
        if not opts['apply']:
            self.stdout.write(self.style.NOTICE(
                'Dry run — re-run with --apply to write these changes.'))
            return

        updated = Question.objects.filter(
            id__in=[q.id for q in matched],
        ).update(answer_format=Question.ANSWER_FORMAT_PATTERN)
        self.stdout.write(self.style.SUCCESS(
            f"Updated {updated} question(s) to answer_format='pattern'."))
