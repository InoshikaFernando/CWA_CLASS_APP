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

The same is owed on "complete the pattern: 30, ___, 60, 75, ___, ___. What is
the rule?", whose Answer rows hold only the rule: a student who wrote the
missing numbers beside it — everything the question asked for — matched none of
them and was marked wrong until the grader learned to read such an answer
against the pattern the question prints. Both defects are short_answer / text,
so one run of this command gives those marks back.

The evidence needed to put it right is already stored: StudentAnswer.text_answer
holds what the child actually typed. This re-runs today's grader over it.

ONE DIRECTION ONLY — wrong to right, never right to wrong. A mark already
awarded stays awarded. Taking a mark back from a child months later, because
grading got stricter, is not a decision a script should make on its own.

WHAT IS RE-GRADED
  Typed answers whose result is a pure function of the stored data:
  short_answer / fill_blank / calculation, in the text / set / algebra /
  equation / pattern formats — across all three places a maths answer is
  recorded:

    quiz        maths.StudentAnswer
    homework    homework.HomeworkStudentAnswer  (auto-graded rows only)
    worksheets  worksheets.WorksheetStudentAnswer

  The comma-splitting defect was the quiz's alone — homework and worksheets
  always called grade_text_answer directly. But the rules that fixed term
  order ("110+12p" for "12p + 110") and division notation ("n/4" for "n ÷ 4")
  live in that shared method, so those two stores are owed marks as well.

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

from maths.models import StudentAnswer
from maths.regrade_support import (
    fix_results, fix_submissions, format_changes, quiz_changes,
    rebuild_statistics, submission_changes,
)

# Typed answers, graded by Question.grade_text_answer.
REGRADABLE_TYPES = ('short_answer', 'fill_blank', 'calculation')
REGRADABLE_FORMATS = ('text', 'set', 'algebra', 'equation', 'pattern')


def now_correct(question, raw):
    """Does today's grader accept what this student typed?"""
    return question.grade_text_answer(raw)


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
        parser.add_argument(
            '--source', choices=('all', 'quiz', 'homework', 'worksheets'),
            default='all', help='Which record of answers to re-grade.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the corrections. Without this the '
                                 'command only reports (dry run).')

    # ------------------------------------------------------------------
    def _regradable(self, question):
        return (question.question_type in REGRADABLE_TYPES
                and question.answer_format in REGRADABLE_FORMATS
                and not question.needs_grading)

    def _scan(self, rows, opts):
        """Rows marked wrong whose recorded text the grader now accepts."""
        examined = 0
        found = []
        for row in rows.iterator(chunk_size=500):
            if opts['limit'] and examined >= opts['limit']:
                break
            examined += 1
            question = row.question
            if question is None or not self._regradable(question):
                continue
            if question.grade_text_answer(row.text_answer):
                found.append(row)
        return examined, found

    def _quiz_rows(self, opts):
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
        return rows

    def _homework_rows(self, opts):
        """Auto-graded homework answers only.

        review_status records who marked the row. A row awaiting or carrying an
        AI or teacher verdict is theirs, not this command's — re-running a
        grader over it would overwrite a person's judgement.
        """
        from homework.models import HomeworkStudentAnswer

        rows = (
            HomeworkStudentAnswer.objects
            .filter(is_correct=False,
                    review_status=HomeworkStudentAnswer.REVIEW_AUTO)
            .exclude(text_answer='')
            .exclude(question__isnull=True)
            .select_related('question', 'question__topic', 'question__level',
                            'submission')
            .prefetch_related('question__answers')
            .order_by('id')
        )
        if opts['topic'] is not None:
            rows = rows.filter(question__topic_id=opts['topic'])
        if opts['student'] is not None:
            rows = rows.filter(submission__student_id=opts['student'])
        if opts['question'] is not None:
            rows = rows.filter(question_id=opts['question'])
        return rows

    def _worksheet_rows(self, opts):
        from worksheets.models import WorksheetStudentAnswer

        rows = (
            WorksheetStudentAnswer.objects
            .filter(is_correct=False)
            .exclude(text_answer='')
            .exclude(question__isnull=True)
            .select_related('question', 'question__topic', 'question__level',
                            'submission')
            .prefetch_related('question__answers')
            .order_by('id')
        )
        if opts['topic'] is not None:
            rows = rows.filter(question__topic_id=opts['topic'])
        if opts['student'] is not None:
            rows = rows.filter(submission__student_id=opts['student'])
        if opts['question'] is not None:
            rows = rows.filter(question_id=opts['question'])
        return rows

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        wanted = opts['source']
        sources = []
        if wanted in ('all', 'quiz'):
            sources.append(('quiz', self._quiz_rows(opts)))
        if wanted in ('all', 'homework'):
            sources.append(('homework', self._homework_rows(opts)))
        if wanted in ('all', 'worksheets'):
            sources.append(('worksheets', self._worksheet_rows(opts)))

        found_by_source = {}
        for name, rows in sources:
            examined, found = self._scan(rows, opts)
            found_by_source[name] = found
            self.stdout.write(
                f'{name:<11} examined {examined:>5}, owed a mark: {len(found)}')

        found = found_by_source.get('quiz', [])
        homework_found = found_by_source.get('homework', [])
        worksheet_found = found_by_source.get('worksheets', [])
        total_found = len(found) + len(homework_found) + len(worksheet_found)

        self.stdout.write('')
        self.stdout.write(f'Marked wrong, now grade correct : {total_found}')

        if not total_found:
            self.stdout.write(self.style.SUCCESS(
                'Nothing to correct — no past answer is owed a mark.'))
            return

        students = {row.student_id for row in found}
        students |= {row.submission.student_id
                     for row in homework_found + worksheet_found}
        questions = {row.question_id for row in found}
        questions |= {row.question_id
                      for row in homework_found + worksheet_found}
        self.stdout.write(f'Students affected               : {len(students)}')
        self.stdout.write(f'Questions affected              : {len(questions)}')
        self.stdout.write('')

        by_question = defaultdict(list)
        for row in found + homework_found + worksheet_found:
            by_question[row.question].append(row)
        for question, rows in list(by_question.items())[:10]:
            year = question.level.level_number if question.level_id else '?'
            topic = question.topic.name if question.topic_id else '(no topic)'
            self.stdout.write(f'  Q{question.id} [year {year} / {topic}] '
                              f'{question.question_text[:60]}')
            self.stdout.write(f'      stored : {question.correct_answer_display()[:70]}')
            for row in rows[:3]:
                student = getattr(row, 'student_id', None)
                if student is None:
                    student = row.submission.student_id
                self.stdout.write(f'      student {student} typed '
                                  f'{row.text_answer[:50]!r} — was marked wrong')
        if len(by_question) > 10:
            self.stdout.write(f'  … and {len(by_question) - 10} more question(s)')

        changes = self._score_changes(found, homework_found, worksheet_found)
        self._report_changes(changes)

        if not opts['apply']:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                'Dry run — re-run with --apply to correct these marks.'))
            return

        with transaction.atomic():
            for row in found + homework_found + worksheet_found:
                row.is_correct = True
                row.points_earned = row.question.points
                row.save(update_fields=['is_correct', 'points_earned'])

            results_fixed, stats_keys = fix_results(
                students, questions, now_correct)
            submissions_fixed, self.lowered = fix_submissions(
                homework_found, worksheet_found)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Corrected {total_found} answer(s) for {len(students)} student(s).'))
        self.stdout.write(self.style.SUCCESS(
            f'Recounted {results_fixed} quiz result(s) and '
            f'{submissions_fixed} homework/worksheet submission(s).'))

        for label, pk, kept, recount in getattr(self, 'lowered', []):
            self.stdout.write(self.style.WARNING(
                f'  {label} submission {pk}: stored score {kept} is higher than '
                f'its answers justify ({recount}). Kept {kept} — no mark taken '
                f'away — but the two disagree and something put them out of step.'))

        rebuilt = rebuild_statistics(stats_keys)
        if rebuilt:
            self.stdout.write(self.style.SUCCESS(
                f'Rebuilt statistics for {rebuilt} topic/level pair(s).'))

    # ------------------------------------------------------------------
    def _score_changes(self, found, homework_found, worksheet_found):
        """What each affected mark goes from, and to — projected, not written,
        so the dry run shows exactly what --apply would do."""
        return (submission_changes('homework', homework_found)
                + submission_changes('worksheets', worksheet_found)
                + quiz_changes(found, now_correct))

    def _report_changes(self, changes):
        for line in format_changes(changes):
            self.stdout.write(line)
