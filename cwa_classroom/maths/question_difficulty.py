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

# How many DISTINCT wrong answers are shown per row. Three is enough to tell
# the two cases apart at a glance: seven children typing seven different things
# is a hard question, seven children typing the same thing is the answer key or
# the accepted format — and the second is the one this dashboard exists to
# catch. The row says how many more distinct answers there were, so three is
# never mistaken for all of them.
GIVEN_TOP_N = 3

# How many candidates are re-checked against the live Question rows at a time
# while filling the list. Purely a query-size choice — the loop keeps going
# until it has TOP_N live questions or the candidates run out, so a run of
# retired questions at the top costs another round trip, never a short list.
_PAGE = 200

# How many candidate ids are checked against the live Question rows at a time
# while counting the bands. Bigger than _PAGE because this query carries ids
# only — the band summary covers every ranked question, not the ten on show,
# and a bank the size of this one ranks thousands.
_LIVE_CHUNK = 2000

# The severity bands the panel summarises by, worst first. Each is
# ``(low, high, label)`` and reads as low <= rate <= high, so the boundaries
# cannot overlap and no question falls between two bands.
#
# 100% is its own band rather than the top of a 75-and-up one because it means
# something different: not one child in the whole sample got it right, which
# for a question five or more children have sat is nearly always the answer
# key rather than the children.
WRONG_RATE_BANDS = (
    (100.0, 100.0, 'Always wrong'),
    (75.0, 99.9, '75–99% wrong'),
    (50.0, 74.9, '50–74% wrong'),
    (25.0, 49.9, '25–49% wrong'),
    (0.1, 24.9, 'Under 25% wrong'),
)

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


def ranked_questions(min_attempts=MIN_ATTEMPTS):
    """``(candidates, tally, cutoffs)`` — every question with evidence to rank.

    Split out of :func:`wrong_rate_rows` so the top ten and the band summary
    beside them are built from ONE pass over the answer store. Counting twice
    would double the cost of the page and, worse, let the two disagree if an
    answer arrived between the passes — a summary that does not add up to the
    list under it is the kind of contradiction this dashboard exists to avoid.

    Each candidate is ``(percent, attempts, question_id)``, worst rate first.
    Liveness is NOT applied here: it costs a query per batch and both callers
    apply it as they walk, each over the slice it actually needs.
    """
    from .models import StudentAnswer

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
    return candidates, tally, cutoffs


def wrong_rate_bands(candidates):
    """How many ranked questions sit in each severity band.

    The list beside this shows ten rows. Ten is what a person can act on, but
    it is also all they can see, so a bank with four hundred always-wrong
    questions and one with eleven look identical on it — the same ten rows at
    100%. The bands are the size of the problem behind the list: they count
    EVERY question that qualifies to rank, which is what makes "we are getting
    through them" a readable claim rather than a feeling.

    Retired and deleted questions are dropped here exactly as they are from the
    rows, or the summary would total more than the list it heads could ever
    reach.
    """
    from .models import Question

    ids = [question_id for _p, _a, question_id in candidates]
    live = set()
    for start in range(0, len(ids), _LIVE_CHUNK):
        live.update(
            Question.objects
            .filter(id__in=ids[start:start + _LIVE_CHUNK],
                    retired_at__isnull=True)
            .values_list('id', flat=True))

    counts = {label: 0 for _low, _high, label in WRONG_RATE_BANDS}
    total = 0
    for percent, _attempts, question_id in candidates:
        if question_id not in live:
            continue
        total += 1
        for low, high, label in WRONG_RATE_BANDS:
            if low <= percent <= high:
                counts[label] += 1
                break
    return {
        'bands': [{'label': label, 'low': low, 'high': high,
                   'count': counts[label]}
                  for low, high, label in WRONG_RATE_BANDS],
        'total': total,
    }


def wrong_rate_rows(*, limit=TOP_N, min_attempts=MIN_ATTEMPTS, ranked=None):
    """The questions costing students the most marks, worst rate first.

    Each row is ``{'question', 'attempts', 'wrong', 'percent', 'since'}``.
    ``since`` is the review date the count starts from, or ``None`` when the
    whole history is counted because nobody has reviewed it yet — the
    difference between "80% of everyone who ever sat it" and "80% of the eight
    children who sat it since it was last checked", which a reviewer has to be
    able to tell apart.

    ``ranked`` is the :func:`ranked_questions` triple, passed in by a caller
    that also wants the band summary so the scan is paid for once.
    """
    from .models import Question

    candidates, tally, cutoffs = (
        ranked if ranked is not None else ranked_questions(min_attempts))

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
            # For the "expected" half of the evidence on each row. One query
            # for the page, against one per row if the template reached for
            # them itself.
            .prefetch_related('answers')
        }
        given = wrong_answers_given(list(live), cutoffs)
        for percent, attempts, question_id in page:
            question = live.get(question_id)
            if question is None:
                continue          # retired, or deleted since the tally
            wrong = tally[question_id][1]
            answers_given = given.get(question_id, {'top': [], 'others': 0})
            rows.append({
                'question': question,
                'attempts': attempts,
                'wrong': wrong,
                'percent': percent,
                'since': cutoffs.get(question_id),
                # The evidence behind the percentage: what they answered, and
                # what the question would have accepted.
                'given': answers_given['top'],
                'given_others': answers_given['others'],
                'expected': expected_answer(question),
            })
            if len(rows) >= limit:
                break
    return rows


def wrong_answers_given(question_ids, cutoffs, top=GIVEN_TOP_N):
    """What students actually answered, per question, commonest first.

    The rate says a question is costing marks; it cannot say why, and the two
    reasons look identical from the percentage alone. Seven children typing
    seven different things is a hard question doing its job. Seven children
    typing the SAME thing — "148" where the key holds "148 g", "1/2" where it
    holds "0.5" — is the question marking a correct answer wrong, which is the
    fault this whole dashboard is for. Only the answers themselves tell them
    apart, so the row carries them.

    Counted over the same answers the rate is: wrong ones only, and for a
    reviewed question only those given since its review, or the row would
    explain a percentage with evidence that percentage does not include.

    ``{question_id: {'top': [{'text', 'count'}], 'others': n}}``. Grouping is
    done by the database, so a question thousands have sat costs one row per
    distinct answer rather than one per child.
    """
    from .models import StudentAnswer

    ids = list(question_ids)
    if not ids:
        return {}

    clause = Q()
    for question_id in ids:
        cutoff = cutoffs.get(question_id)
        clause |= (Q(question_id=question_id, answered_at__gt=cutoff)
                   if cutoff else Q(question_id=question_id))

    counts = defaultdict(lambda: defaultdict(int))
    spelling = {}
    for row in (StudentAnswer.objects
                .filter(clause, is_correct=False)
                .values('question_id', 'text_answer',
                        'selected_answer__answer_text')
                .annotate(n=Count('id'))):
        text = (row['selected_answer__answer_text']
                or row['text_answer'] or '').strip()
        # Folded so "Twelve" and "twelve" are one answer given twelve times
        # rather than two given once — the whole point is spotting the answer
        # many children agreed on. The first spelling seen is what is shown.
        key = text.casefold()
        counts[row['question_id']][key] += row['n']
        spelling.setdefault((row['question_id'], key), text)

    out = {}
    for question_id, tally in counts.items():
        ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        out[question_id] = {
            'top': [{'text': spelling[(question_id, key)], 'count': n}
                    for key, n in ordered[:top]],
            'others': max(0, len(ordered) - top),
        }
    return out


def expected_answer(question):
    """What the question accepts, as a reader of the row would state it.

    Printed beside what the children gave, because the comparison is the whole
    diagnosis: "expected 148 g, seven children typed 148" is a marking rule to
    fix, and nothing about either half says that on its own.

    ``question.answers`` must already be prefetched — this is called once per
    row on a page that has just fetched them.
    """
    accepted = [answer.answer_text.strip()
                for answer in question.answers.all()
                if answer.is_correct and (answer.answer_text or '').strip()]
    if accepted:
        return accepted
    if question.numeric_answer is not None:
        unit = (question.answer_unit or '').strip()
        return [f'{question.numeric_answer}{" " + unit if unit else ""}']
    return []


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
