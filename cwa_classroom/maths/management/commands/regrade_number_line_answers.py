"""Give back the marks lost to a number-line inequality graph's broken key.

A student graphed "k <= -2" on a -7..7 line by marking -7 -6 -5 -4 -3 -2, and
"m > 1" by marking 2 3 4 5 6 7. Both are right. Both were marked wrong, because
the stored answer key was a spelled-out list of ticks that stopped one short —
the closed boundary on the <=, the line's own end tick on the >.

``repair_number_line_inequalities`` fixes the QUESTION. It does not touch the
marks already given: grading happens once, at submission, and the verdict is
written into the answer row, the attempt score, the review payload the child and
their teacher read months later, and the statistics built on top. Repairing the
key alone leaves every past attempt still saying the child got it wrong.

This is the other half. The evidence needed is already stored — the ticks the
student actually marked, as the ``{"marks": [...]}`` payload the client sent —
so this re-runs today's grader over it.

    python manage.py repair_number_line_inequalities --apply   # fix the questions
    python manage.py regrade_number_line_answers --apply       # then the marks

WHAT IS RE-GRADED
  Answers to number-line questions whose spec now STATES its inequality — the
  ones the repair command converted, where we know the key was corrected to
  match the question as printed. Across all three places a maths answer is
  recorded:

    quiz        maths.StudentAnswer
    homework    homework.HomeworkStudentAnswer  (auto-graded rows only)
    worksheets  worksheets.WorksheetStudentAnswer

WHAT IS NOT, and why
  * Number-line questions with a plain spelled-out target. Their key was never
    derived from anything, so a difference between it and today's grading means
    someone EDITED the question — and the children who answered it answered the
    old one. Re-marking them against a question they never saw is not a
    correction.
  * Read-mode questions. The defect was in a mark-mode answer key; a typed
    read-off was never affected.
  * Teacher- and AI-marked homework rows. A person or a model judged those, and
    re-running a grader over them would overwrite that judgement.

ONE DIRECTION ONLY — wrong to right, never right to wrong. This matters more
here than it did for the typed regrade: under the broken key, the student who
marked -7..-3 and LEFT OUT the boundary was marked right. The repaired key says
otherwise. That mark stays. Taking it back months later, because the question it
was earned on turned out to be misprinted, is not a decision a script makes —
and it is not the child's mistake to pay for.

DRY-RUN BY DEFAULT. Idempotent: a corrected row grades correct, and correct rows
are never examined again.

    python manage.py regrade_number_line_answers                 # dry run
    python manage.py regrade_number_line_answers --question 9710
    python manage.py regrade_number_line_answers --student 31
    python manage.py regrade_number_line_answers --apply
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from maths.geometry_grading import (
    grade_number_line, number_line_targets, spec_inequality,
)
from maths.models import Question, StudentAnswer
from maths.regrade_support import (
    fix_results, fix_submissions, format_changes, quiz_changes,
    rebuild_statistics, submission_changes,
)


def in_scope(question):
    """Is this a question whose key was corrected to match what it prints?

    Only an inequality graph carrying its ``inequality`` block qualifies: the
    tick set is derived from the question itself, so re-grading a past answer
    against it marks that answer against the question the child was actually
    shown. A hand-listed target carries no such guarantee.
    """
    return (question is not None
            and question.question_type == Question.NUMBER_LINE
            and spec_inequality(question.number_line_spec or {}) is not None)


def now_correct(question, raw):
    """Does today's key accept the ticks this student marked?"""
    if not in_scope(question):
        return False
    return grade_number_line(question.number_line_spec, raw)


class Command(BaseCommand):
    help = ('Re-mark past number-line answers that a corrected inequality key '
            'now accepts, and correct the scores and statistics built on them.')

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
    def _scan(self, rows, opts):
        """Rows marked wrong whose recorded marks the corrected key accepts."""
        examined = 0
        found = []
        for row in rows.iterator(chunk_size=500):
            if opts['limit'] and examined >= opts['limit']:
                break
            examined += 1
            if now_correct(row.question, row.text_answer):
                found.append(row)
        return examined, found

    def _narrow(self, rows, opts, student_field):
        if opts['topic'] is not None:
            rows = rows.filter(question__topic_id=opts['topic'])
        if opts['student'] is not None:
            rows = rows.filter(**{student_field: opts['student']})
        if opts['question'] is not None:
            rows = rows.filter(question_id=opts['question'])
        return rows

    def _base(self, model, **extra):
        """Wrong, non-blank answers to number-line questions, newest last.

        Narrowed to the type in SQL; ``in_scope`` then decides per question,
        since "carries an inequality block" lives inside the JSON spec.
        """
        return (model.objects
                .filter(is_correct=False,
                        question__question_type=Question.NUMBER_LINE,
                        **extra)
                .exclude(text_answer='')
                .exclude(question__isnull=True)
                .select_related('question', 'question__topic', 'question__level')
                .order_by('id'))

    def _quiz_rows(self, opts):
        return self._narrow(self._base(StudentAnswer), opts, 'student_id')

    def _homework_rows(self, opts):
        """Auto-graded homework answers only — a row awaiting or carrying an AI
        or teacher verdict is theirs, not this command's."""
        from homework.models import HomeworkStudentAnswer

        rows = self._base(HomeworkStudentAnswer,
                          review_status=HomeworkStudentAnswer.REVIEW_AUTO)
        return self._narrow(rows.select_related('submission'), opts,
                            'submission__student_id')

    def _worksheet_rows(self, opts):
        from worksheets.models import WorksheetStudentAnswer

        rows = self._base(WorksheetStudentAnswer)
        return self._narrow(rows.select_related('submission'), opts,
                            'submission__student_id')

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
                'Nothing to correct — no past answer is owed a mark. (Run '
                'repair_number_line_inequalities --apply first if the questions '
                'themselves have not been fixed yet.)'))
            return

        students = {row.student_id for row in found}
        students |= {row.submission.student_id
                     for row in homework_found + worksheet_found}
        questions = {row.question_id for row in found}
        questions |= {row.question_id for row in homework_found + worksheet_found}
        self.stdout.write(f'Students affected               : {len(students)}')
        self.stdout.write(f'Questions affected              : {len(questions)}')
        self.stdout.write('')

        by_question = defaultdict(list)
        for row in found + homework_found + worksheet_found:
            by_question[row.question].append(row)
        for question, rows in list(by_question.items())[:10]:
            year = question.level.level_number if question.level_id else '?'
            topic = question.topic.name if question.topic_id else '(no topic)'
            op, value = spec_inequality(question.number_line_spec)
            self.stdout.write(f'  Q{question.id} [year {year} / {topic}] '
                              f'{question.question_text.strip()[:60]}')
            self.stdout.write(
                f'      key now {op} {value} → '
                f'{number_line_targets(question.number_line_spec)}')
            for row in rows[:3]:
                student = getattr(row, 'student_id', None)
                if student is None:
                    student = row.submission.student_id
                self.stdout.write(f'      student {student} marked '
                                  f'{row.text_answer[:50]} — was marked wrong')
        if len(by_question) > 10:
            self.stdout.write(f'  … and {len(by_question) - 10} more question(s)')

        changes = (submission_changes('homework', homework_found)
                   + submission_changes('worksheets', worksheet_found)
                   + quiz_changes(found, now_correct))
        for line in format_changes(changes):
            self.stdout.write(line)

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
            submissions_fixed, lowered = fix_submissions(
                homework_found, worksheet_found)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Corrected {total_found} answer(s) for {len(students)} student(s).'))
        self.stdout.write(self.style.SUCCESS(
            f'Recounted {results_fixed} quiz result(s) and '
            f'{submissions_fixed} homework/worksheet submission(s).'))

        for label, pk, kept, recount in lowered:
            self.stdout.write(self.style.WARNING(
                f'  {label} submission {pk}: stored score {kept} is higher than '
                f'its answers justify ({recount}). Kept {kept} — no mark taken '
                f'away — but the two disagree and something put them out of step.'))

        rebuilt = rebuild_statistics(stats_keys)
        if rebuilt:
            self.stdout.write(self.style.SUCCESS(
                f'Rebuilt statistics for {rebuilt} topic/level pair(s).'))
