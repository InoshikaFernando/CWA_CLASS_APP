"""Give back the marks a wrong answer key took (CPP wrong-answer leaderboard).

Fixing a question's answer key fixes it *from that moment on*. Every child who
already sat it keeps the nought: in their history, in their teacher's view, and
in the progress statistics built on top. That is the half of the repair the
editor never did, and the half a parent actually notices.

``regrade_question`` closes it. Called after a save that changed how a question
marks, it re-marks every answer already recorded against the key as it now
stands, and corrects the attempt totals and topic statistics those marks sit
inside.

ONE DIRECTION ONLY — wrong to right, never right to wrong.
    A mark already awarded stays awarded, exactly as
    ``manage.py regrade_typed_answers`` decided for the same question. Taking a
    mark back from a child weeks later, because an adult changed their mind
    about the answer, is not a consequence a Save button may have. Where a fix
    means some previously-correct answers are now wrong, the honest remedy is
    to retire the question, not to re-mark downwards — and that is a decision
    with a person's name on it.

WHAT IS RE-MARKED
    quiz        maths.StudentAnswer
    homework    homework.HomeworkStudentAnswer  (auto-graded rows only)
    worksheets  worksheets.WorksheetStudentAnswer

    A chosen option is re-read from the row the student actually picked, which
    is stored, so "is this now the correct option?" is a fact and not a guess.
    A typed answer is re-graded by today's grader over the text the student
    typed, which is also stored.

WHAT IS NOT
    * AI-graded and human-graded questions — a model or a person reached that
      verdict, and re-running either is a re-roll, not a correction.
    * Homework rows carrying an AI or teacher verdict (``review_status``),
      for the same reason: that mark is somebody's judgement, not this key's.
    * Spec-graded types — measure, number_line, draw_on_grid, plot_*,
      table_of_values, shape_select, prime_factorization. Their answer is a
      payload marked against a stored figure by a different grader, and
      ``grade_text_answer`` reading it as plain text would not re-mark those
      rows, it would award marks nobody earned. Drag-and-drop orderings are
      out for the same reason.

    ``grades_from_text`` below is the one definition of which typed answers
    are a pure function of the stored data. ``manage.py regrade_typed_answers``
    — the bulk twin of this module — imports it rather than keeping a second
    copy that could drift, because a rule about who may be awarded a mark must
    not have two readings.
"""
from django.db import transaction


class Regraded:
    """What one re-mark actually changed, in the words a reviewer needs.

    A bare count of rows says nothing about whether anybody's mark moved, so
    this carries the students and the attempt totals as well — and stays
    falsey when nothing was owed, so a caller can stay silent instead of
    announcing a correction that did not happen.
    """

    def __init__(self):
        self.quiz = 0
        self.homework = 0
        self.worksheets = 0
        self.attempts = 0          # StudentFinalAnswer rows recounted
        self.submissions = 0       # homework / worksheet submissions recounted
        self.students = set()

    @property
    def answers(self):
        return self.quiz + self.homework + self.worksheets

    def __bool__(self):
        return bool(self.answers)

    def summary(self):
        """One sentence, or '' when nothing was owed."""
        if not self.answers:
            return ''
        marks = f'{self.answers} answer{"s" if self.answers != 1 else ""}'
        kids = (f'{len(self.students)} student'
                f'{"s" if len(self.students) != 1 else ""}')
        return (f'{marks} from {kids} had been marked wrong by the old answer '
                f'and are now marked correct.')


# Typed answers whose verdict ``Question.grade_text_answer`` owns outright.
TYPED_REGRADABLE_TYPES = ('short_answer', 'fill_blank', 'calculation',
                          'column_operation', 'long_division')
TYPED_REGRADABLE_FORMATS = ('text', 'set', 'algebra', 'equation', 'pattern')

# The two worked out from the question's own numbers rather than its Answer
# rows. answer_format plays no part in that verdict, so it must not narrow what
# is re-marked: these are regradable whatever format they were saved with. One
# missing its numbers grades against its rows like any other typed answer, and
# the format rule above decides it.
SELF_GRADED_ARITHMETIC_TYPES = ('column_operation', 'long_division')


def can_regrade(question):
    """True if this question's marks are a pure function of its stored data.

    Anything a model or a person marked is theirs, and re-running it would be a
    re-roll rather than a correction.
    """
    return not (question.is_ai_graded or question.needs_grading)


def grades_from_text(question):
    """True if ``grade_text_answer`` is the grader that marked this question.

    The gate that keeps a spec-graded answer — an angle measured off a figure,
    a point plotted on a plane — away from a text matcher that would read its
    stored payload as a string and hand out marks nobody earned.
    """
    if question.needs_grading:
        return False
    if question.question_type in SELF_GRADED_ARITHMETIC_TYPES:
        from maths.column_grading import grade_self_graded_arithmetic
        # None means the question cannot work its own answer out, so it is
        # graded against its rows and the ordinary rule below decides it.
        if grade_self_graded_arithmetic(question, '') is not None:
            return True
    return (question.question_type in TYPED_REGRADABLE_TYPES
            and question.answer_format in TYPED_REGRADABLE_FORMATS)


def correct_answer_ids(question):
    return {answer.id for answer in question.answers.all() if answer.is_correct}


def _now_correct(question, row, correct_ids):
    """Does today's key mark this already-recorded answer correct?

    A stored ``selected_answer`` settles it outright whatever the question
    type: the student picked that row, and whether the row is now ticked
    correct is a fact rather than a re-grading. Everything else needs the
    text grader, which only some questions are its to mark.
    """
    if row.selected_answer_id is not None:
        return row.selected_answer_id in correct_ids
    if not grades_from_text(question):
        return False
    text = (row.text_answer or '').strip()
    if not text:
        return False
    return bool(question.grade_text_answer(text))


def regrade_question(question):
    """Re-mark past answers to ``question`` against its current answer key.

    Returns a :class:`Regraded`. Does nothing, and says so by returning an
    empty one, for a question this must not re-mark (see ``can_regrade``).
    """
    result = Regraded()
    if not can_regrade(question):
        return result

    correct_ids = correct_answer_ids(question)

    with transaction.atomic():
        quiz_rows = _flip(_quiz_rows(question), question, correct_ids)
        homework_rows = _flip(_homework_rows(question), question, correct_ids)
        worksheet_rows = _flip(_worksheet_rows(question), question, correct_ids)

        result.quiz = len(quiz_rows)
        result.homework = len(homework_rows)
        result.worksheets = len(worksheet_rows)
        result.students = (
            {row.student_id for row in quiz_rows}
            | {row.submission.student_id
               for row in homework_rows + worksheet_rows})

        if not result:
            return result

        result.attempts = _fix_quiz_attempts(
            question, {row.student_id for row in quiz_rows})
        result.submissions = _fix_submissions(homework_rows, worksheet_rows)

    return result


# ── the three answer stores ───────────────────────────────────────────────

def _quiz_rows(question):
    from .models import StudentAnswer

    return (StudentAnswer.objects
            .filter(question=question, is_correct=False)
            .select_related('selected_answer'))


def _homework_rows(question):
    """Auto-graded homework rows only — an AI or teacher verdict is theirs."""
    from homework.models import HomeworkStudentAnswer

    return (HomeworkStudentAnswer.objects
            .filter(question=question, is_correct=False,
                    review_status=HomeworkStudentAnswer.REVIEW_AUTO)
            .select_related('selected_answer', 'submission'))


def _worksheet_rows(question):
    from worksheets.models import WorksheetStudentAnswer

    return (WorksheetStudentAnswer.objects
            .filter(question=question, is_correct=False)
            .select_related('selected_answer', 'submission'))


def _flip(rows, question, correct_ids):
    """Mark right every row the current key says was right all along."""
    flipped = []
    for row in rows:
        if not _now_correct(question, row, correct_ids):
            continue
        row.is_correct = True
        row.points_earned = question.points
        row.save(update_fields=['is_correct', 'points_earned'])
        flipped.append(row)
    return flipped


# ── the totals those marks sit inside ─────────────────────────────────────

def _payload_now_correct(question, entry, correct_texts):
    """Re-mark one entry of a stored quiz review payload.

    ``StudentFinalAnswer`` keeps its own session id rather than the answers'
    ``attempt_id``, so the two stores cannot be joined —
    ``regrade_typed_answers`` documents the same wall. They do not need to be:
    the payload stores what the student themselves answered, which is the same
    evidence, and re-reading that is what keeps an attempt's total honest with
    the marks underneath it.

    A chosen option is recorded as its text (``quiz.views`` writes
    ``answer.answer_text``), so a choice question is settled by matching that
    text against the options the key now calls correct.
    """
    raw = entry.get('student_answer')
    if raw is None or isinstance(raw, (list, dict, bool)):
        return False
    typed = str(raw).strip()
    if not typed:
        return False
    if correct_texts is not None:
        return typed.casefold() in correct_texts
    if not grades_from_text(question):
        return False
    return bool(question.grade_text_answer(typed))


def _fix_quiz_attempts(question, student_ids):
    """Recount every stored attempt of these students that holds this question."""
    from .models import Question, StudentFinalAnswer, TopicLevelStatistics, calculate_points

    if not student_ids:
        return 0

    choice = question.question_type in (Question.MULTIPLE_CHOICE,
                                        Question.TRUE_FALSE)
    correct_texts = (
        {(answer.answer_text or '').strip().casefold()
         for answer in question.answers.all() if answer.is_correct}
        if choice else None)

    fixed = 0
    stats_keys = set()
    for result in (StudentFinalAnswer.objects
                   .filter(student_id__in=student_ids)
                   .select_related('topic', 'level')
                   .iterator(chunk_size=200)):
        entries = result.questions_data or []
        if not isinstance(entries, list):
            continue
        changed = False
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('is_correct'):
                continue
            if entry.get('id') != question.id:
                continue
            if _payload_now_correct(question, entry, correct_texts):
                entry['is_correct'] = True
                changed = True
        if not changed:
            continue

        score = sum(1 for entry in entries
                    if isinstance(entry, dict) and entry.get('is_correct'))
        # Never downwards: a stored score higher than its own payload justifies
        # was set by something else (partial credit, a manual adjustment), and
        # a re-mark that is only ever owed marks must not take one away.
        result.score = max(result.score or 0, score)
        result.points = calculate_points(
            result.score, result.total_questions,
            result.time_taken_seconds or 1)
        result.questions_data = entries
        result.save(update_fields=['score', 'points', 'questions_data'])
        fixed += 1
        if result.topic_id and result.level_id:
            stats_keys.add((result.topic, result.level))

    for topic, level in stats_keys:
        TopicLevelStatistics.recalculate(topic, level)
    return fixed


def _fix_submissions(homework_rows, worksheet_rows):
    """Recount the homework and worksheet totals the flipped marks sit inside.

    Each app owns the arithmetic for its own totals, so this calls theirs
    rather than keeping a second opinion that could drift — the same division
    of labour ``regrade_typed_answers`` settled on.
    """
    from homework.views import _recalculate_submission_score

    fixed = 0
    seen = set()
    for row in homework_rows:
        submission = row.submission
        if submission.pk in seen:
            continue
        seen.add(submission.pk)
        before = submission.score or 0
        _recalculate_submission_score(submission)
        submission.refresh_from_db()
        _never_lower(submission, before)
        fixed += 1

    seen = set()
    for row in worksheet_rows:
        submission = row.submission
        if submission.pk in seen:
            continue
        seen.add(submission.pk)
        before = submission.score or 0
        submission.score = submission.answers.filter(is_correct=True).count()
        submission.save(update_fields=['score'])
        _never_lower(submission, before)
        fixed += 1
    return fixed


def _never_lower(submission, before):
    """A recount must not take a mark away — see the module docstring."""
    if (submission.score or 0) >= before:
        return
    submission.score = before
    submission.save(update_fields=['score'])
