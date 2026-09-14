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
  equation / pattern formats, plus column_operation / long_division, which are
  worked out from the question's own numbers — across all three places a maths
  answer is recorded:

    quiz        maths.StudentAnswer
    homework    homework.HomeworkStudentAnswer  (auto-graded rows only)
    worksheets  worksheets.WorksheetStudentAnswer

  The comma-splitting defect was the quiz's alone — homework and worksheets
  always called grade_text_answer directly. But the rules that fixed term
  order ("110+12p" for "12p + 110") and division notation ("n/4" for "n ÷ 4")
  live in that shared method, so those two stores are owed marks as well.

  Column arithmetic and long division, since the quiz learned to grade them.
  These are worked out from the question's own numbers, so they carry no
  Answer row — and the quiz, which had no branch for them, dropped them into
  the answer-row fallback and scored every submission zero: 867 x 8 answered
  6936 was marked wrong for every child who ever typed it. Worksheets and
  homework graded them from the numbers all along, so most of what is owed
  here is the quiz's — but a long division spelled "12r0" rather than
  "12 r 0" was refused on a worksheet too, and is owed as well.

WHAT IS NOT, and why
  * multiple choice / true-false / drag-drop — graded from the row the student
    picked, and those rules have not changed.
  * measure, number_line, draw_on_grid, plot_*, table_of_values, shape_select,
    prime_factorization — graded against a spec by a different code path, not
    grade_text_answer.
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

from maths.answer_key_regrade import grades_from_text
from maths.models import (
    Question, StudentAnswer, StudentFinalAnswer, TopicLevelStatistics,
    calculate_points,
)


def typed_answer(entry):
    """Read a student's typed answer out of a stored quiz review payload.

    questions_data is JSON written by the quiz view, and a bare numeric answer
    can land in it as a number rather than a string, so this coerces instead of
    assuming str. Zero has to survive that coercion — "0" is a real answer to a
    maths question, not a blank — which is why this cannot be `or ''`. A list
    or dict is not a typed answer at all, so it reads as blank.
    """
    raw = entry.get('student_answer')
    if raw is None or isinstance(raw, (list, dict, bool)):
        return ''
    return str(raw).strip()


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
    # Which typed answers grade_text_answer owns outright lives in
    # maths.answer_key_regrade, because the same rule decides what the question
    # editor's Save may re-mark. A rule about who may be awarded a mark must
    # not have two readings that can drift apart.
    def _regradable(self, question):
        return grades_from_text(question)

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

            results_fixed, stats_keys = self._fix_results(students, questions)
            submissions_fixed = self._fix_submissions(
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

        for topic, level in stats_keys:
            TopicLevelStatistics.recalculate(topic, level)
        if stats_keys:
            self.stdout.write(self.style.SUCCESS(
                f'Rebuilt statistics for {len(stats_keys)} topic/level pair(s).'))

    # ------------------------------------------------------------------
    def _score_changes(self, found, homework_found, worksheet_found):
        """What each affected mark goes from, and to.

        A count of corrected answers does not tell anyone what a child's mark
        actually was and will become — which is the only form a teacher or a
        parent can act on. Computed without writing anything, so the dry run
        shows exactly what --apply would do.
        """
        changes = []

        # Homework and worksheets: the owed rows belong to a submission whose
        # score counts its correct answers, so the new score is the old one
        # plus the rows about to flip.
        for label, rows in (('homework', homework_found),
                            ('worksheets', worksheet_found)):
            per_submission = defaultdict(list)
            for row in rows:
                per_submission[row.submission].append(row)
            for submission, owed in per_submission.items():
                before = submission.score or 0
                # Project the way --apply counts — from the answer rows — not
                # from the stored score. Where the two disagree the stored
                # score is already wrong, and a dry run that quietly assumed it
                # was right would promise a number apply then would not write.
                after = (submission.answers.filter(is_correct=True).count()
                         + len(owed))
                changes.append((
                    label, submission.student_id, f'submission {submission.pk}',
                    before, max(before, after),
                    submission.total_questions or 0))

        # Quiz: the attempt total is recounted from the stored review payload,
        # so the projection re-grades that payload rather than assuming.
        if found:
            questions = {row.question_id for row in found}
            cache = {q.id: q for q in Question.objects.filter(id__in=questions)
                     .prefetch_related('answers')}
            students = {row.student_id for row in found}
            for result in (StudentFinalAnswer.objects
                           .filter(student_id__in=students)
                           .iterator(chunk_size=200)):
                entries = result.questions_data or []
                if not isinstance(entries, list):
                    continue
                flips = 0
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get('is_correct'):
                        continue
                    question = cache.get(entry.get('id'))
                    typed = typed_answer(entry)
                    if question and typed and question.grade_text_answer(typed):
                        flips += 1
                if flips:
                    before = result.score or 0
                    changes.append((
                        'quiz', result.student_id, f'attempt {result.pk}',
                        before, before + flips, result.total_questions or 0))
        return changes

    def _report_changes(self, changes):
        if not changes:
            return
        self.stdout.write('')
        self.stdout.write('Marks before → after:')
        by_student = defaultdict(list)
        for change in changes:
            by_student[change[1]].append(change)
        for student in sorted(by_student):
            self.stdout.write(f'  student {student}')
            for label, _sid, what, before, after, total in sorted(by_student[student]):
                out_of = f'/{total}' if total else ''
                self.stdout.write(
                    f'      {label:<11} {what:<16} '
                    f'{before}{out_of} → {after}{out_of}   (+{after - before})')

    # ------------------------------------------------------------------
    def _fix_submissions(self, homework_found, worksheet_found):
        """Recount the homework and worksheet totals the marks sit inside.

        Each app already owns the arithmetic for its own totals, so this calls
        theirs rather than keeping a second copy that could drift: homework
        counts correct answers and sums points_earned, worksheets count correct
        answers. Recomputing either here would be a third opinion on a sum that
        already has an owner.
        """
        from homework.views import _recalculate_submission_score

        fixed = 0
        self.lowered = []
        seen = set()
        for row in homework_found:
            submission = row.submission
            if submission.pk in seen:
                continue
            seen.add(submission.pk)
            before = submission.score or 0
            _recalculate_submission_score(submission)
            submission.refresh_from_db()
            self._never_lower('homework', submission, before)
            fixed += 1

        seen = set()
        for row in worksheet_found:
            submission = row.submission
            if submission.pk in seen:
                continue
            seen.add(submission.pk)
            before = submission.score or 0
            submission.score = submission.answers.filter(is_correct=True).count()
            submission.save(update_fields=['score'])
            self._never_lower('worksheets', submission, before)
            fixed += 1
        return fixed

    def _never_lower(self, label, submission, before):
        """A recount must not take a mark away.

        The totals are recounted from the answer rows. Where a stored score is
        already higher than its rows justify — a manual adjustment, or grading
        that ran after the score was written — recounting would quietly drop
        the child's mark, which is not what this command was asked to do. The
        old score is kept and the disagreement is reported, because a score
        that does not match its own answers is worth someone looking at.
        """
        if (submission.score or 0) >= before:
            return
        recount = submission.score
        submission.score = before
        submission.save(update_fields=['score'])
        self.lowered.append((label, submission.pk, before, recount))

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
                typed = typed_answer(entry)
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
