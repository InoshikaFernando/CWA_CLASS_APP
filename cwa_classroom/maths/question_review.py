"""Who has reported a question, and whether a human has cleared it (CPP-398).

The rules that decide whether a "Reviewed and correct" verdict still stands
live here rather than on the model, because every caller needs them answered in
bulk: the live check page runs over 1,000 questions a click, and the nightly
``record_question_health`` walks the whole ~19,500-question bank. A per-row
property would turn either into thousands of queries.

Both tables are human-made — somebody clicked Report, somebody clicked
Reviewed — so they stay small next to the question bank, and :class:`ReviewState`
loads them once up front and then answers per question without touching the
database again.
"""

from datetime import timedelta

# How far back the dashboard's "just reviewed" strip looks when offering to undo
# a verdict. A verdict older than this is not one somebody is still undoing by
# mistake, and listing a month-old review under "just reviewed" would be the
# panel lying about what it shows.
RECENT_REVIEW_DAYS = 7
RECENT_REVIEW_LIMIT = 10

# The issue code a reported question is raised under. It comes from the report
# rows, not from ``verify_question``: the verifier has already passed the
# question the student is complaining about, which is precisely why the
# complaint matters.
USER_REPORTED = 'USER-REPORTED'


class ReviewState:
    """Report and clearance state for a set of questions, loaded once.

    ``question_ids`` narrows the load to a batch; ``None`` loads every report
    and review there is, which is what the whole-bank recorder wants and is
    affordable because both tables only grow when a person acts.
    """

    def __init__(self, question_ids=None):
        from .models import QuestionReport, QuestionReview

        ids = None if question_ids is None else list(question_ids)
        if ids is not None and not ids:
            self._latest_review = {}
            self._reports = {}
            return

        reviews = QuestionReview.objects.all()
        reports = QuestionReport.objects.all()
        if ids is not None:
            reviews = reviews.filter(question_id__in=ids)
            reports = reports.filter(question_id__in=ids)

        # Only the most recent review counts, whatever its verdict — an old
        # 'correct' must never outrank a newer 'broken'. The ordering does the
        # grouping, so the first row seen per question is the one that stands.
        self._latest_review = {}
        for row in (reviews
                    .order_by('question_id', '-reviewed_at')
                    .values('question_id', 'verdict', 'reviewed_at',
                            'question_updated_at')):
            self._latest_review.setdefault(row['question_id'], row)

        self._reports = {}
        for row in (reports
                    .order_by('-created_at')
                    .values('question_id', 'note', 'created_at',
                            'feedback_id')):
            self._reports.setdefault(row['question_id'], []).append(row)

    # ── Reports ───────────────────────────────────────────────────────────

    def open_reports(self, question):
        """Reports on ``question`` that no later review has answered.

        A report filed before the latest review has been judged, whichever way
        the verdict went, so it stops being an open complaint. One filed after
        it is still open — including on a question the reviewer passed, which
        is what makes a second, independent complaint resurface it.
        """
        rows = self._reports.get(_id_of(question), ())
        review = self._latest_review.get(_id_of(question))
        if review is None:
            return list(rows)
        return [r for r in rows if r['created_at'] > review['reviewed_at']]

    def report_count(self, question):
        return len(self.open_reports(question))

    # ── Clearance ─────────────────────────────────────────────────────────

    def is_cleared(self, question):
        """True if a "reviewed and correct" verdict on ``question`` still holds.

        ``question`` must be a Question instance here — the check reads its
        ``updated_at`` off the object already in hand rather than re-fetching
        it. A clearance stops applying when the question is edited after the
        review, when a newer review says it is broken, or when somebody reports
        it again afterwards. Each of those is a reason to look once more, and
        suppressing a question through any of them would be the dashboard
        vouching for text nobody checked — the failure this module exists to
        prevent.
        """
        from .models import QuestionReview

        review = self._latest_review.get(question.id)
        if review is None or review['verdict'] != QuestionReview.VERDICT_CORRECT:
            return False

        reviewed_version = review['question_updated_at']
        edited = getattr(question, 'updated_at', None)
        if edited and reviewed_version and edited > reviewed_version:
            return False                  # edited since — the clearance is stale
        if self.open_reports(question):
            return False                  # reported again — new evidence
        return True


def _id_of(question):
    return question if isinstance(question, int) else question.id


def report_detail(reports):
    """The Problem-column text for a question's open reports."""
    count = len(reports)
    lead = ('Reported by a user' if count == 1
            else f'Reported by {count} users')
    note = (reports[0]['note'] or '').strip().replace('\n', ' ')
    return f'{lead}: “{note[:160]}”' if note else lead


def record_review(question, *, user, verdict, note=''):
    """Record one human verdict on ``question`` and return the row.

    The content version is snapshotted here rather than left to the caller: a
    review saved without it never goes stale, and would go on vouching for text
    somebody edited afterwards.
    """
    from .models import QuestionReview

    return QuestionReview.objects.create(
        question=question,
        reviewed_by=user if (user and user.is_authenticated) else None,
        verdict=verdict,
        note=note or '',
        question_updated_at=question.updated_at,
    )


def recent_reviews(*, days=RECENT_REVIEW_DAYS, limit=RECENT_REVIEW_LIMIT):
    """The verdicts recorded lately, newest first — what the undo strip lists.

    Only the verdict that CURRENTLY stands for a question is listed. Undoing a
    superseded one would delete somebody's reading of the question without
    changing anything any dashboard shows — history lost and nothing undone,
    the worst of both. A replacement verdict is by definition newer than the
    row it replaced, so it falls inside this window too and is the row that
    appears here.
    """
    from django.utils import timezone

    from .models import QuestionReview

    cutoff = timezone.now() - timedelta(days=days)
    rows, seen = [], set()
    for review in (QuestionReview.objects
                   .filter(reviewed_at__gte=cutoff)
                   .select_related('question', 'question__level',
                                   'question__topic', 'question__topic__parent',
                                   'reviewed_by')
                   .order_by('-reviewed_at')):
        if review.question_id in seen:
            continue                      # already replaced by a later verdict
        seen.add(review.question_id)
        rows.append(review)
        if len(rows) >= limit:
            break
    return rows


def is_latest_review(review):
    """True if ``review`` is the verdict standing on its question right now.

    Undo deletes a row, so it may only ever touch this one: deleting an
    older verdict would rewrite what a person concluded while leaving the
    verdict actually in force untouched.
    """
    from .models import QuestionReview

    return not (QuestionReview.objects
                .filter(question_id=review.question_id,
                        reviewed_at__gt=review.reviewed_at)
                .exists())
