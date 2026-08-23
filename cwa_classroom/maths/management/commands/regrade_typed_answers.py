"""
regrade_typed_answers
~~~~~~~~~~~~~~~~~~~~~
Re-mark past typed answers that the grader has since learned to accept, and
give the students back the marks they lost.

Why this exists: grading rules get fixed, but the marks already recorded do
not move. A student who typed "40, 36, 28" for a stored "40, 36, 28" was
scored WRONG, because the old grader split the stored answer on commas and
looked for a whole answer equal to "40", or "36", or "28". The fix (CPP-378)
changed grading from that day forward and left every past attempt saying the
child got it wrong — in their history, in their teacher's view, and in the
progress statistics built on top.

The evidence needed to put it right is already stored: StudentAnswer.text_answer
holds what the child actually typed. This re-runs today's grader over it.

ONE DIRECTION ONLY — wrong to right, never right to wrong. A mark already
awarded stays awarded. Taking a mark back from a child months later, because
grading got stricter, is not a decision a script should make on its own.

WHAT IS RE-GRADED
  Typed answers whose result is a pure function of the stored data:
  short_answer / fill_blank / calculation, in the text / set / algebra /
  equation / pattern formats.

WHAT IS NOT, and why
  * multiple choice / true-false / drag-drop — graded from the row the student
    picked, and those rules have not changed.
  * measure, number_line, draw_on_grid, plot_*, table_of_values, shape_select,
    long_division, prime_factorization, column_operation — graded against a
    spec by a different code path, not grade_text_answer.
  * ai_graded / human_graded / extended_answer — a model or a person judged
    them. Re-running an AI grader over historical answers would cost money and
    could return a different verdict on the same text, which is not a
    correction, it is a re-roll.

Aggregates are corrected too: each affected StudentFinalAnswer has the entry in
its questions_data re-marked, its score recounted and its points recomputed
with the same formula the quiz uses, and the topic/level statistics rebuilt.
Leaving the attempt totals stale would fix the detail and keep the summary
wrong.

Usage (run from cwa_classroom/):
    python manage.py regrade_typed_answers                    # dry run
    python manage.py regrade_typed_answers --topic 147
    python manage.py regrade_typed_answers --student 31
    python manage.py regrade_typed_answers --apply
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from maths.models import (
    Question, StudentAnswer, StudentFinalAnswer, TopicLevelStatistics,
    calculate_points,
)

# Typed answers, graded by Question.grade_text_answer.
REGRADABLE_TYPES = ('short_answer', 'fill_blank', 'calculation')
REGRADABLE_FORMATS = ('text', 'set', 'algebra', 'equation', 'pattern')


class Command(BaseCommand):
    help = ('Re-mark past typed answers the grader now accepts, and correct the '
            'attempt scores and statistics that were built on them.')

    def add_arguments(self, parser):
        parser.add_argument('--topic', type=int, default=None,
                            help='Limit to one topic id.')
        parser.add_argument('--student', type=int, default=None,
                            help='Limit to one student id.')
        parser.add_argument('--question', type=int, default=None,
                            help='Limit to one question id.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Stop after examining N answers (smoke run).')
        parser.add_argument('--apply', action='store_true',
                            help='Write the corrections. Without this the '
                                 'command only reports (dry run).')

    # ------------------------------------------------------------------
    def _regradable(self, question):
        return (question.question_type in REGRADABLE_TYPES
                and question.answer_format in REGRADABLE_FORMATS
                and not question.needs_grading)

    def _find(self, opts):
        """Answers marked wrong whose recorded text the grader now accepts."""
        rows = (
            StudentAnswer.objects
            .filter(is_correct=False)
            .exclude(text_answer='')
            .select_related('question', 'question__topic', 'question__level')
            .prefetch_related('question__answers')
            .order_by('id')
        )
        if opts['topic'] is not None:
            rows = rows.filter(question__topic_id=opts['topic'])
        if opts['student'] is not None:
            rows = rows.filter(student_id=opts['student'])
        if opts['question'] is not None:
            rows = rows.filter(question_id=opts['question'])

        examined = 0
        found = []
        for row in rows.iterator(chunk_size=500):
            if opts['limit'] and examined >= opts['limit']:
                break
            examined += 1
            question = row.question
            if not self._regradable(question):
                continue
            if question.grade_text_answer(row.text_answer):
                found.append(row)
        return examined, found

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        examined, found = self._find(opts)

        self.stdout.write(f'Answers examined                : {examined}')
        self.stdout.write(f'Marked wrong, now grade correct : {len(found)}')

        if not found:
            self.stdout.write(self.style.SUCCESS(
                'Nothing to correct — no past answer is owed a mark.'))
            return

        students = {row.student_id for row in found}
        questions = {row.question_id for row in found}
        self.stdout.write(f'Students affected               : {len(students)}')
        self.stdout.write(f'Questions affected              : {len(questions)}')
        self.stdout.write('')

        by_question = defaultdict(list)
        for row in found:
            by_question[row.question].append(row)
        for question, rows in list(by_question.items())[:10]:
            year = question.level.level_number if question.level_id else '?'
            topic = question.topic.name if question.topic_id else '(no topic)'
            self.stdout.write(f'  Q{question.id} [year {year} / {topic}] '
                              f'{question.question_text[:60]}')
            self.stdout.write(f'      stored : {question.correct_answer_display()[:70]}')
            for row in rows[:3]:
                self.stdout.write(f'      student {row.student_id} typed '
                                  f'{row.text_answer[:50]!r} — was marked wrong')
        if len(by_question) > 10:
            self.stdout.write(f'  … and {len(by_question) - 10} more question(s)')

        if not opts['apply']:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                'Dry run — re-run with --apply to correct these marks.'))
            return

        with transaction.atomic():
            for row in found:
                row.is_correct = True
                row.points_earned = row.question.points
                row.save(update_fields=['is_correct', 'points_earned'])

            results_fixed, stats_keys = self._fix_results(students, questions)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Corrected {len(found)} answer(s) for {len(students)} student(s).'))
        self.stdout.write(self.style.SUCCESS(
            f'Recounted {results_fixed} quiz result(s).'))

        for topic, level in stats_keys:
            TopicLevelStatistics.recalculate(topic, level)
        if stats_keys:
            self.stdout.write(self.style.SUCCESS(
                f'Rebuilt statistics for {len(stats_keys)} topic/level pair(s).'))

    # ------------------------------------------------------------------
    def _fix_results(self, students, questions):
        """Re-mark the stored review payloads and recount the attempt scores.

        StudentFinalAnswer carries its own session id rather than the answers'
        attempt_id, so the two cannot be joined. They do not need to be: each
        result stores the student's own words per question in questions_data,
        which is the same evidence, and re-grading that is what keeps the
        attempt total honest with the answers underneath it.
        """
        fixed = 0
        stats_keys = set()
        results = (
            StudentFinalAnswer.objects
            .filter(student_id__in=students)
            .select_related('topic', 'level')
        )
        cache = {q.id: q for q in
                 Question.objects.filter(id__in=questions)
                 .prefetch_related('answers')}

        for result in results.iterator(chunk_size=200):
            entries = result.questions_data or []
            if not isinstance(entries, list):
                continue
            changed = False
            for entry in entries:
                if not isinstance(entry, dict) or entry.get('is_correct'):
                    continue
                question = cache.get(entry.get('id'))
                typed = (entry.get('student_answer') or '').strip()
                if not question or not typed:
                    continue
                if question.grade_text_answer(typed):
                    entry['is_correct'] = True
                    changed = True
            if not changed:
                continue

            result.score = sum(1 for e in entries
                               if isinstance(e, dict) and e.get('is_correct'))
            result.points = calculate_points(
                result.score, result.total_questions,
                result.time_taken_seconds or 1)
            result.questions_data = entries
            result.save(update_fields=['score', 'points', 'questions_data'])
            fixed += 1
            if result.topic_id and result.level_id:
                stats_keys.add((result.topic, result.level))
        return fixed, stats_keys
