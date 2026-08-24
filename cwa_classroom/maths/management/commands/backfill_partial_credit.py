"""
backfill_partial_credit
~~~~~~~~~~~~~~~~~~~~~~~
Give back the marks that all-or-nothing grading took off past answers to
questions that ask for more than one value.

Why this exists: a fill-in-the-blank sentence and a table of values are several
answers in one question, but were marked all-or-nothing. A money chart with
nine of ten cells filled in correctly scored zero. Grading was fixed from that
day forward (see ``maths.partial_credit``) and every attempt already recorded
still says the child got nothing — in their history, in their teacher's view,
and in the totals built on top.

The evidence needed to put it right is already stored: the answer row holds the
raw payload the student submitted, gap by gap. This re-runs today's grader over
it and awards the share they earned.

ONE DIRECTION ONLY — a stored mark is never lowered. Not a row's points, not a
submission's score, not a submission's points. Taking a mark back from a child
months later is not a decision a script makes on its own. Where a stored total
is higher than its own rows justify, the total is kept and the disagreement is
reported, because that is worth a person looking at.

WHAT IS BACKFILLED
  Auto-graded answers to part-graded questions (``fill_blank`` with a
  ``blank_spec``, ``table_of_values`` with a ``table_spec``) in the two stores
  that keep both the raw payload and a per-answer points field:

    homework    homework.HomeworkStudentAnswer   (review_status=auto_graded)
    worksheets  worksheets.WorksheetStudentAnswer

  A row whose payload no longer lines up with its question's spec gets no
  per-gap verdict and is left alone rather than credited on a guess.

WHAT IS NOT, and why
  * Quiz attempts (maths.StudentFinalAnswer). The attempt total would have to
    be recomputed from the answers underneath it, and the two cannot be joined:
    StudentFinalAnswer carries its own session id, not the answers' attempt_id.
    Its stored review payload holds only the READABLE form of the answer
    ("15, live"), not the payload that was graded, so re-grading it gap by gap
    would be guessing which value belonged to which gap. Counted rather than
    touched, and reported at the end so the gap is visible instead of silent.
  * Rows a teacher or the AI grader has marked (any review_status other than
    auto_graded) — those marks are somebody's judgement, not this script's.
  * Rows already worth at least what today's grader says they are.

Dry run by default; ``--apply`` writes.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from maths.models import Question, calculate_points
from maths.partial_credit import credit_from_answer_data, points_for

# The question types that are marked one gap at a time. Each needs its spec:
# without it there is nothing to grade the gaps against.
PART_GRADED = {
    Question.FILL_BLANK: 'blank_spec',
    Question.TABLE_OF_VALUES: 'table_spec',
}


def is_part_graded(question):
    """Is this question marked gap by gap (and does it still carry its spec)?"""
    spec_field = PART_GRADED.get(question.question_type)
    return bool(spec_field and getattr(question, spec_field, None))


class Command(BaseCommand):
    help = ('Award partial credit on past answers to fill-in-the-blank and '
            'table-of-values questions, and correct the totals built on them.')

    def add_arguments(self, parser):
        parser.add_argument('--student', type=int, default=None,
                            help='Limit to one student id.')
        parser.add_argument('--question', type=int, default=None,
                            help='Limit to one question id.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Stop after examining N answers (smoke run).')
        parser.add_argument(
            '--source', choices=('all', 'homework', 'worksheets'), default='all',
            help='Which record of answers to re-score.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the corrections. Without this the '
                                 'command only reports (dry run).')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.lowered = []
        # Submissions whose points are on the AI/teacher-graded scale — their
        # rows are re-scored, their points total is left as graded.
        self.graded_elsewhere = []
        source = opts['source']

        homework_owed = ([] if source == 'worksheets'
                         else self._scan(self._homework_rows(opts), opts))
        worksheet_owed = ([] if source == 'homework'
                          else self._scan(self._worksheet_rows(opts), opts))

        total = len(homework_owed) + len(worksheet_owed)
        if not total:
            self.stdout.write(self.style.SUCCESS(
                'No answer is owed partial credit — nothing to backfill.'))
            self._report_quiz_gap(opts)
            return

        self._report_rows('homework', homework_owed)
        self._report_rows('worksheets', worksheet_owed)

        if not opts['apply']:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                f'Dry run — {total} answer(s) would be re-scored. Re-run with '
                f'--apply to write them.'))
            self._report_quiz_gap(opts)
            return

        with transaction.atomic():
            for row, grade, points in homework_owed + worksheet_owed:
                self._award(row, grade, points)
            submissions = (self._fix_homework(homework_owed)
                           + self._fix_worksheets(worksheet_owed))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Re-scored {total} answer(s) and recounted '
            f'{submissions} submission(s).'))
        if self.graded_elsewhere:
            self.stdout.write(self.style.WARNING(
                f'  {len(self.graded_elsewhere)} homework submission(s) also '
                f'carry AI- or teacher-graded answers, so their points total is '
                f'on the graded scale (a sum of per-answer points) rather than '
                f'the submit formula. Their rows were re-scored and their '
                f'points left as graded: {self.graded_elsewhere}'))
        for label, pk, kept, recount in self.lowered:
            self.stdout.write(self.style.WARNING(
                f'  {label} submission {pk}: stored total {kept} is higher than '
                f'its answers justify ({recount}). Kept {kept} — no mark taken '
                f'away — but the two disagree and something put them out of step.'))
        self._report_quiz_gap(opts)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def _homework_rows(self, opts):
        from homework.models import HomeworkStudentAnswer

        rows = (HomeworkStudentAnswer.objects
                .filter(review_status=HomeworkStudentAnswer.REVIEW_AUTO,
                        question__question_type__in=PART_GRADED)
                .select_related('question', 'submission'))
        if opts['student']:
            rows = rows.filter(submission__student_id=opts['student'])
        if opts['question']:
            rows = rows.filter(question_id=opts['question'])
        return rows

    def _worksheet_rows(self, opts):
        from worksheets.models import WorksheetStudentAnswer

        rows = (WorksheetStudentAnswer.objects
                .filter(question__question_type__in=PART_GRADED)
                .select_related('question', 'submission'))
        if opts['student']:
            rows = rows.filter(submission__student_id=opts['student'])
        if opts['question']:
            rows = rows.filter(question_id=opts['question'])
        return rows

    def _scan(self, rows, opts):
        """Rows worth more under gap-by-gap marking than they were given.

        Returns ``[(row, grade, points)]``. Computes without writing, so the
        dry run reports exactly what --apply would do.
        """
        examined = 0
        owed = []
        for row in rows.iterator(chunk_size=500):
            if opts['limit'] and examined >= opts['limit']:
                break
            examined += 1
            question = row.question
            if question is None or not is_part_graded(question):
                continue
            grade = question.grade_text_answer_parts(row.text_answer)
            if grade is None or not grade.correct:
                # No per-gap verdict, or nothing right — nothing is owed, and a
                # payload that will not line up is never credited on a guess.
                continue
            points = points_for(question.points, grade)
            if points <= (row.points_earned or 0):
                continue
            owed.append((row, grade, points))
        return owed

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def _award(self, row, grade, points):
        row.points_earned = points
        # Merge rather than replace: whatever else the row carried (a coding
        # payload, an older grader's notes) is not this command's to discard.
        row.answer_data = {**(row.answer_data or {}), **grade.as_answer_data()}
        fields = ['points_earned', 'answer_data']
        if grade.is_correct and not row.is_correct:
            # Today's grader accepts every gap. Wrong → right only; a row
            # already marked correct is never un-marked.
            row.is_correct = True
            fields.append('is_correct')
        row.save(update_fields=fields)

    def _fix_homework(self, owed):
        """Recount each touched homework submission's score and points.

        Points are recomputed the way the SUBMIT path computes them — the
        speed-and-accuracy formula over the credit earned — because that is the
        scale the number on this submission is already on.

        A submission that has been through AI or teacher grading is not on that
        scale: ``_recalculate_submission_score`` rewrote its points as the sum
        of its rows' points_earned, a different quantity entirely. Recomputing
        it with the formula would replace one meaning with another and call it
        a correction, so those submissions get their score recounted and their
        points left exactly as graded — reported, not silently skipped.
        """
        from homework.models import HomeworkStudentAnswer

        fixed = 0
        for submission in self._submissions(owed):
            rows = list(submission.answers.all())
            score = sum(1 for r in rows if r.is_correct)
            all_auto = all(r.review_status == HomeworkStudentAnswer.REVIEW_AUTO
                           for r in rows)
            if all_auto:
                credit = sum(credit_from_answer_data(r.answer_data, r.is_correct)
                             for r in rows)
                points = calculate_points(
                    credit, submission.total_questions or len(rows) or 1,
                    submission.time_taken_seconds or 1)
            else:
                points = None
                self.graded_elsewhere.append(submission.pk)
            self._save_totals('homework', submission, score, points)
            fixed += 1
        return fixed

    def _fix_worksheets(self, owed):
        """Recount each touched worksheet submission's score.

        A worksheet submission stores a count of correct answers and no points
        total, so this moves only when a row's every gap turned out right.
        """
        fixed = 0
        for submission in self._submissions(owed):
            score = submission.answers.filter(is_correct=True).count()
            self._save_totals('worksheets', submission, score, None)
            fixed += 1
        return fixed

    @staticmethod
    def _submissions(owed):
        seen = {}
        for row, _grade, _points in owed:
            seen.setdefault(row.submission_id, row.submission)
        return list(seen.values())

    def _save_totals(self, label, submission, score, points):
        """Write the recounted totals, never below what is already stored."""
        fields = []
        if score > (submission.score or 0):
            submission.score = score
            fields.append('score')
        elif score < (submission.score or 0):
            self.lowered.append((label, submission.pk, submission.score, score))

        if points is not None:
            if points > (submission.points or 0):
                submission.points = points
                fields.append('points')
            elif points < (submission.points or 0):
                self.lowered.append(
                    (f'{label} points', submission.pk, submission.points, points))
        if fields:
            submission.save(update_fields=fields)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _report_rows(self, label, owed):
        if not owed:
            return
        self.stdout.write('')
        self.stdout.write(f'{label}: {len(owed)} answer(s) owed partial credit')
        by_student = defaultdict(list)
        for row, grade, points in owed:
            by_student[row.submission.student_id].append((row, grade, points))
        for student in sorted(by_student):
            self.stdout.write(f'  student {student}')
            for row, grade, points in by_student[student][:5]:
                self.stdout.write(
                    f'      Q{row.question_id} {grade.correct}/{grade.total} '
                    f'{grade.noun}s right — '
                    f'{row.points_earned or 0} → {points} point(s)')
            if len(by_student[student]) > 5:
                self.stdout.write(
                    f'      … and {len(by_student[student]) - 5} more answer(s)')

    def _report_quiz_gap(self, opts):
        """Say plainly what this command cannot reach, and why.

        A backfill that silently skipped a whole store would read as "the quiz
        had nothing owed", which is not the same thing at all.
        """
        if opts['source'] not in ('all',):
            return
        from maths.models import StudentAnswer

        rows = StudentAnswer.objects.filter(
            question__question_type__in=PART_GRADED)
        if opts['student']:
            rows = rows.filter(student_id=opts['student'])
        if opts['question']:
            rows = rows.filter(question_id=opts['question'])
        count = rows.count()
        if not count:
            return
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            f'{count} quiz answer(s) to part-graded questions were NOT '
            f're-scored: a quiz attempt total cannot be recomputed from them '
            f'(StudentFinalAnswer stores its own session id, so the two cannot '
            f'be joined, and its saved review payload holds only the readable '
            f'form of the answer). Quiz scoring is correct from the day partial '
            f'credit shipped; past attempts keep the marks they were given.'))
