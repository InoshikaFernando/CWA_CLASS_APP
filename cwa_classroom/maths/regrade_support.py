"""Shared machinery for the regrade commands — giving back marks already given.

Re-marking a past answer is never just the answer row. A mark sits inside an
attempt score, a submission total, a stored review payload the student and their
teacher read months later, and the topic/level statistics built on all of it.
Correcting the row and leaving those behind fixes the detail and keeps the
summary wrong.

That plumbing is identical whatever made the old mark wrong, so it lives here
once and each command supplies only the part that differs: a
``now_correct(question, raw)`` predicate saying whether the evidence already
stored grades correct TODAY.

    regrade_typed_answers          the grader learned to accept what was typed
    regrade_number_line_answers    the question's answer key was wrong

TWO RULES HOLD FOR EVERY CALLER, and they are enforced here rather than trusted
to each command:

  * ONE DIRECTION ONLY — wrong to right, never right to wrong. An entry already
    marked correct is skipped before the predicate is even consulted. Taking a
    mark back from a child months later is not a decision a script makes.
  * A SUBMISSION RECOUNT NEVER LOWERS A TOTAL. Where a stored homework or
    worksheet score is already higher than its own rows justify, the score
    stands and the disagreement is reported.

NOT a rule, and worth knowing before you run either command: a QUIZ ATTEMPT
score carries no such guard. ``fix_results`` recounts it from the review payload
— the only per-question record an attempt has — so an attempt whose stored score
already disagreed with its own payload is rewritten to what the payload says,
which can be LOWER. That is longstanding behaviour of regrade_typed_answers,
kept here deliberately rather than quietly changed: the two guards belong
together, and making them agree is a decision for whoever owns the attempt
score, not a side effect of adding a second caller.
"""
from collections import defaultdict

from maths.models import (
    Question, StudentFinalAnswer, TopicLevelStatistics, calculate_points,
)


def payload_answer(entry):
    """Read a student's stored answer out of a quiz review payload.

    questions_data is JSON written by the quiz view, and a bare numeric answer
    can land in it as a number rather than a string, so this coerces instead of
    assuming str. Zero has to survive that coercion — "0" is a real answer to a
    maths question, not a blank — which is why this cannot be `or ''`. A list or
    dict is not an answer any grader here reads, so it reads as blank.
    """
    raw = entry.get('student_answer')
    if raw is None or isinstance(raw, (list, dict, bool)):
        return ''
    return str(raw).strip()


# ---------------------------------------------------------------------------
# Projection — what the dry run promises, computed without writing anything.
# ---------------------------------------------------------------------------

def submission_changes(label, rows):
    """``(label, student, what, before, after, total)`` per homework/worksheet.

    A count of corrected answers does not tell anyone what a child's mark
    actually was and will become — the only form a teacher or a parent can act
    on. The projection counts from the ANSWER ROWS, the way applying does, not
    from the stored score: where the two disagree the stored score is already
    wrong, and a dry run that assumed it was right would promise a number that
    apply then would not write.
    """
    changes = []
    per_submission = defaultdict(list)
    for row in rows:
        per_submission[row.submission].append(row)
    for submission, owed in per_submission.items():
        before = submission.score or 0
        after = submission.answers.filter(is_correct=True).count() + len(owed)
        changes.append((label, submission.student_id, f'submission {submission.pk}',
                        before, max(before, after), submission.total_questions or 0))
    return changes


def quiz_changes(rows, now_correct):
    """``(…)`` per quiz attempt whose stored payload is owed marks.

    The attempt total is recounted from the stored review payload, so the
    projection re-grades that payload rather than assuming the answer rows and
    the payload agree.
    """
    if not rows:
        return []
    questions = {row.question_id for row in rows}
    cache = _question_cache(questions)
    students = {row.student_id for row in rows}
    changes = []
    for result in (StudentFinalAnswer.objects
                   .filter(student_id__in=students)
                   .iterator(chunk_size=200)):
        flips = _count_flips(result, cache, now_correct)
        if flips:
            before = result.score or 0
            changes.append(('quiz', result.student_id, f'attempt {result.pk}',
                            before, before + flips, result.total_questions or 0))
    return changes


def format_changes(changes):
    """The "before → after" block, as lines. Empty when nothing changes."""
    if not changes:
        return []
    lines = ['', 'Marks before → after:']
    by_student = defaultdict(list)
    for change in changes:
        by_student[change[1]].append(change)
    for student in sorted(by_student):
        lines.append(f'  student {student}')
        for label, _sid, what, before, after, total in sorted(by_student[student]):
            out_of = f'/{total}' if total else ''
            lines.append(f'      {label:<11} {what:<16} '
                         f'{before}{out_of} → {after}{out_of}   (+{after - before})')
    return lines


# ---------------------------------------------------------------------------
# Writing — the totals a corrected mark sits inside.
# ---------------------------------------------------------------------------

def fix_submissions(homework_rows, worksheet_rows):
    """Recount the homework and worksheet totals. ``(fixed, lowered)``.

    Each app already owns the arithmetic for its own totals, so this calls
    theirs rather than keeping a second copy that could drift: homework counts
    correct answers and sums points_earned, worksheets count correct answers.
    Recomputing either here would be a third opinion on a sum that already has
    an owner.

    ``lowered`` lists ``(label, pk, kept, recount)`` for any submission whose
    stored score was already higher than its rows justify — kept as it was, and
    reported, because a score that disagrees with its own answers is worth
    someone looking at.
    """
    from homework.views import _recalculate_submission_score

    fixed, lowered = 0, []

    seen = set()
    for row in homework_rows:
        submission = row.submission
        if submission.pk in seen:
            continue
        seen.add(submission.pk)
        before = submission.score or 0
        _recalculate_submission_score(submission)
        submission.refresh_from_db()
        _never_lower('homework', submission, before, lowered)
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
        _never_lower('worksheets', submission, before, lowered)
        fixed += 1
    return fixed, lowered


def _never_lower(label, submission, before, lowered):
    """A recount must not take a mark away — see this module's docstring."""
    if (submission.score or 0) >= before:
        return
    recount = submission.score
    submission.score = before
    submission.save(update_fields=['score'])
    lowered.append((label, submission.pk, before, recount))


def fix_results(students, questions, now_correct):
    """Re-mark the stored review payloads and recount the attempt scores.

    StudentFinalAnswer carries its own session id rather than the answers'
    attempt_id, so the two cannot be joined. They do not need to be: each result
    stores the student's own answer per question in questions_data, which is the
    same evidence, and re-grading that is what keeps the attempt total honest
    with the answers underneath it.

    Returns ``(results_fixed, stats_keys)`` — the topic/level pairs whose
    statistics the caller must rebuild.
    """
    fixed = 0
    stats_keys = set()
    results = (StudentFinalAnswer.objects
               .filter(student_id__in=students)
               .select_related('topic', 'level'))
    cache = _question_cache(questions)

    for result in results.iterator(chunk_size=200):
        entries = result.questions_data or []
        if not isinstance(entries, list):
            continue
        changed = False
        for entry in _gradable_entries(entries, cache):
            entry_dict, question, raw = entry
            if now_correct(question, raw):
                entry_dict['is_correct'] = True
                changed = True
        if not changed:
            continue

        result.score = sum(1 for e in entries
                           if isinstance(e, dict) and e.get('is_correct'))
        result.points = calculate_points(
            result.score, result.total_questions, result.time_taken_seconds or 1)
        result.questions_data = entries
        result.save(update_fields=['score', 'points', 'questions_data'])
        fixed += 1
        if result.topic_id and result.level_id:
            stats_keys.add((result.topic, result.level))
    return fixed, stats_keys


def rebuild_statistics(stats_keys):
    """Rebuild the topic/level statistics the corrected marks feed."""
    for topic, level in stats_keys:
        TopicLevelStatistics.recalculate(topic, level)
    return len(stats_keys)


# ---------------------------------------------------------------------------

def _question_cache(question_ids):
    return {q.id: q for q in Question.objects.filter(id__in=question_ids)
            .prefetch_related('answers')}


def _gradable_entries(entries, cache):
    """``(entry, question, raw)`` for entries a predicate may still flip.

    Skips anything already marked correct — the one-direction rule — along with
    entries that are not dicts, name a question this run is not about, or carry
    no answer to re-grade.
    """
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('is_correct'):
            continue
        question = cache.get(entry.get('id'))
        raw = payload_answer(entry)
        if not question or not raw:
            continue
        yield entry, question, raw


def _count_flips(result, cache, now_correct):
    entries = result.questions_data or []
    if not isinstance(entries, list):
        return 0
    return sum(1 for _entry, question, raw in _gradable_entries(entries, cache)
               if now_correct(question, raw))
