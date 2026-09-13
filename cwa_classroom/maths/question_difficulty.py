"""Which questions students get wrong most often, and what that is worth.

The rest of the health dashboard reports what the *verifier* can prove about a
question's stored data: no correct option, two identical distractors, an answer
key the arithmetic disagrees with. All of those are faults visible in the row
itself.

This module reports the fault the row cannot show. A question whose answer key
is quietly wrong — 23 where the answer is 23 pencils, a distractor that is the
real answer worded differently — passes every deterministic check and then
marks child after child wrong. The evidence for it is not in the question, it
is in the answers: a wrong-answer rate far above its neighbours' is the only
signal there is.

WHAT IS COUNTED
    ``maths.StudentAnswer`` — the quiz's per-question record — and nothing
    else. Homework and worksheet answers are real answers too, but
    ``HomeworkStudentAnswer`` carries no per-answer timestamp, so the
    "since it was reviewed" rule below could not be applied to it, and a rate
    that silently mixed a filtered store with an unfiltered one would be worse
    than one that says what it covers. The dashboard says so on the panel.

    Retired questions are left out: nobody is being marked by them any more, so
    a reviewer's attention spent on one is attention wasted.

REVIEWED QUESTIONS, AND WHY THE CLOCK RESETS RATHER THAN THE ROW VANISHING
    A super-admin who reads a question and concludes the students simply got it
    wrong needs it gone from the list, or the same ten rows are re-read every
    day and the list stops being read at all. But "gone forever" is the wrong
    promise: the next fifty children may go on getting it wrong, and that is
    new evidence nobody has judged.

    So a review does not hide the question — it *settles the answers recorded
    before it*. Only answers given after the latest review count towards the
    rate, whichever way that review went. A question reviewed today drops off
    immediately (no answers since, so nothing to rank), and comes back on its
    own if it keeps costing students marks afterwards.
"""
from collections import defaultdict

from django.db.models import Count, Q

# Below this, a rate is noise. One child answering once and getting it wrong is
# 100%, and a top-ten list led by questions nobody has really sat is a list that
# points a reviewer away from the questions actually doing damage.
MIN_ATTEMPTS = 5

TOP_N = 10

# How many candidates are re-checked against the live Question rows at a time
# while filling the list. Purely a query-size choice — the loop keeps going
# until it has TOP_N live questions or the candidates run out, so a run of
# retired questions at the top costs another round trip, never a short list.
_PAGE = 200

# Reviews are read in chunks so the "answers since this question's own review"
# filter does not become one enormous OR. The table is human-made — somebody
# clicked Reviewed — so in practice this loops once.
_REVIEW_CHUNK = 200


def _review_cutoffs():
    """``{question_id: when it was last reviewed}``, whatever the verdict.

    A 'needs fixing' verdict settles the past just as a 'correct' one does:
    somebody has looked, and the question is on a person's list. What neither
    settles is what happens next, which is why the cutoff is a date and not a
    flag.
    """
    from .models import QuestionReview

    latest = {}
    for question_id, reviewed_at in (
            QuestionReview.objects
            .order_by('question_id', '-reviewed_at')
            .values_list('question_id', 'reviewed_at')):
        latest.setdefault(question_id, reviewed_at)
    return latest


def _tally(queryset):
    """``{question_id: (attempts, wrong)}`` for one slice of the answer store."""
    return {
        row['question_id']: (row['attempts'], row['wrong'])
        for row in queryset.values('question_id').annotate(
            attempts=Count('id'),
            wrong=Count('id', filter=Q(is_correct=False)),
        )
    }


def _tally_since_review(cutoffs):
    """Answers to reviewed questions that arrived AFTER their own review."""
    from .models import StudentAnswer

    out = {}
    question_ids = sorted(cutoffs)
    for start in range(0, len(question_ids), _REVIEW_CHUNK):
        window = question_ids[start:start + _REVIEW_CHUNK]
        clause = Q()
        for question_id in window:
            clause |= Q(question_id=question_id,
                        answered_at__gt=cutoffs[question_id])
        out.update(_tally(StudentAnswer.objects.filter(clause)))
    return out


def wrong_rate_rows(*, limit=TOP_N, min_attempts=MIN_ATTEMPTS):
    """The questions costing students the most marks, worst rate first.

    Each row is ``{'question', 'attempts', 'wrong', 'percent', 'since'}``.
    ``since`` is the review date the count starts from, or ``None`` when the
    whole history is counted because nobody has reviewed it yet — the
    difference between "80% of everyone who ever sat it" and "80% of the eight
    children who sat it since it was last checked", which a reviewer has to be
    able to tell apart.
    """
    from .models import Question, StudentAnswer

    cutoffs = _review_cutoffs()

    tally = _tally(
        StudentAnswer.objects.exclude(question_id__in=list(cutoffs)))
    tally.update(_tally_since_review(cutoffs))

    candidates = [
        (round(wrong * 100 / attempts, 1), attempts, question_id)
        for question_id, (attempts, wrong) in tally.items()
        if attempts >= min_attempts and wrong
    ]
    # Worst rate first; a tie goes to the question more children have sat,
    # because that is the one costing more marks right now.
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))

    rows = []
    for start in range(0, len(candidates), _PAGE):
        if len(rows) >= limit:
            break
        page = candidates[start:start + _PAGE]
        live = {
            question.id: question
            for question in Question.objects
            .filter(id__in=[question_id for _p, _a, question_id in page],
                    retired_at__isnull=True)
            .select_related('level', 'topic', 'topic__parent', 'topic__subject')
        }
        for percent, attempts, question_id in page:
            question = live.get(question_id)
            if question is None:
                continue          # retired, or deleted since the tally
            wrong = tally[question_id][1]
            rows.append({
                'question': question,
                'attempts': attempts,
                'wrong': wrong,
                'percent': percent,
                'since': cutoffs.get(question_id),
            })
            if len(rows) >= limit:
                break
    return rows


def report_counts(question_ids):
    """``{question_id: open report count}`` for the rows on show.

    A high wrong rate and a student complaint about the same question are the
    same finding arriving by two routes, so the leaderboard says when both are
    present rather than making a reviewer cross-check the other page.
    """
    from .question_review import ReviewState

    state = ReviewState(question_ids)
    counts = defaultdict(int)
    for question_id in question_ids:
        counts[question_id] = state.report_count(question_id)
    return counts
