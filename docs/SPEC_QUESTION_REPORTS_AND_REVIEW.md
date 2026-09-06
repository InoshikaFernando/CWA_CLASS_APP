# Reported Questions & Human Review

**Ticket:** CPP-398 (from the feedback item "[Feedback] repeat")
**Status:** Implemented

## Problem Statement

Two gaps, one loop.

**1. A student who spots a broken question has nowhere to put it.**
The global "Send feedback" button captures a description and the page URL, and
nothing else. CPP-398 is the proof: a Year 7 student wrote *"the answer in
a quality answer was 23 or 23 pencils but why"* against
`/maths/level/7/topic/190/quiz/`. That topic serves dozens of questions, so the
report cannot be traced to the question it is about without guesswork. The
report lands in the Jira queue, and the question stays live, marking students
wrong.

**2. The question-health dashboard has no way to record "I looked, it's fine".**
`verify_question` is deterministic and therefore blunt: `EQUIVALENT-OPTION`
fires on distractors that are equal *as text* but not as intent,
`WRONG-ANSWER-KEY` fires on a question whose arithmetic the evaluator reads
differently from a person. A super-admin who checks such a question and finds
it sound has only two exits — edit it needlessly, or delete it. So the same
false positives are re-read on every run, and a list nobody can shrink is a
list nobody reads.

The two gaps compound: without (2), routing user reports into the health
dashboard would bury the real findings under complaints about questions that
turn out to be correct.

## Design

### The loop

```
student hits a bad question
  → "Report a problem" on the question card
  → Feedback row (as today: Jira bug + Discord) + QuestionReport row
  → question appears as UNHEALTHY on the question-health check page
  → super-admin looks
      ├─ it IS broken  → fix it with the existing bulk fixes / editor
      └─ it is CORRECT → "Reviewed and correct" → QuestionReview(verdict=correct)
                          → suppressed from every unhealthy list
```

### Why a review row rather than a flag on Question

Same reasoning as `QuestionAIReview` (CPP-380): a denormalised
`Question.reviewed_ok` boolean drifts out of sync the moment somebody edits the
question, and then it vouches for text nobody checked. The review row snapshots
`question_updated_at`, so an edit after the review makes the clearance **stale**
rather than silently authoritative.

### When a clearance stops applying

A `QuestionReview(verdict='correct')` suppresses the question from every
unhealthy surface until any one of these:

| Event | Why it re-opens |
|---|---|
| The question is edited (`updated_at` moves past `question_updated_at`) | The reviewer passed different text. |
| A **new** `QuestionReport` arrives after `reviewed_at` | A second independent complaint is new evidence, not the one already judged. |
| A later `QuestionReview(verdict='broken')` is recorded | The most recent human verdict wins. |

Only the **latest** review counts, whatever its verdict — an old `correct` never
outranks a newer `broken`.

### Data Model

```
maths.QuestionReport            "a person said this question is wrong"
  question      FK maths.Question, related_name='reports'
  school        FK classroom.School, null, db_index      # tenant context
  reported_by   FK User, null, SET_NULL                  # evidence outlives the account
  feedback      FK feedback.Feedback, null, SET_NULL, related_name='question_reports'
  note          TextField                                # what they wrote, denormalised
  created_at    DateTimeField(auto_now_add, db_index)
  Meta.ordering = ['-created_at']

maths.QuestionReview            "a person looked and gave a verdict"
  question            FK maths.Question, related_name='human_reviews'
  reviewed_by         FK User, null, SET_NULL
  reviewed_at         DateTimeField(auto_now_add, db_index)
  verdict             'correct' | 'broken'
  note                TextField, blank
  question_updated_at DateTimeField(null)                # content version reviewed
  Meta.ordering = ['-reviewed_at']
  Meta.indexes = [(question, -reviewed_at)]

feedback.Feedback — unchanged. The link is held on QuestionReport so the
dependency arrow runs maths → feedback only.
```

### API

```python
# maths/question_review.py
def open_report_counts(question_ids) -> dict[int, int]
    """Reports per question that no later review has answered."""

def cleared_question_ids(questions) -> set[int]
    """Questions whose 'reviewed and correct' verdict still stands.

    Two queries regardless of batch size — the check page runs this over
    1,000 questions and the nightly recorder over the whole ~19,500 bank.
    """

def record_review(question, *, user, verdict, note='') -> QuestionReview
```

### Surfaces

**Capture — `templates/quiz/partials/topic_question.html`**
A "Report a problem" link under the question card. It loads the existing
feedback modal pre-scoped to the question
(`GET /feedback/submit/?question=<id>`) and dispatches a `report-question`
window event that the launcher in `base.html` / `base_quiz.html` listens for
(`@report-question.window="open = true"`), so there is one modal, not two.

Scoping is enforced on the way in: a question that is neither global nor the
submitter's school 404s on GET. On POST the feedback is **always** saved even if
the question id is unusable — losing what a user typed is worse than losing the
link — but no `QuestionReport` is written and the mismatch is logged.

Times-tables quizzes are out of scope: those questions are generated per
attempt, not rows in the bank, so there is nothing to report against.

**Health — `maths/views_admin.py`, `record_question_health`**
New issue code `USER-REPORTED` ("Reported by a user"), blocking. It is
raised from the report rows rather than from `verify_question`, so a question
with a report is unhealthy even when the verifier likes it — which is the whole
point, since the verifier already passed the question the student is
complaining about.

Both the live check page and the nightly snapshot drop questions with a
standing clearance, so "Reviewed and correct" moves the headline number.

**The review action — `QuestionBulkFixView`**
`mark_reviewed_correct` joins `BULK_ACTIONS` and is added to `MANUAL_FIXES`, so
the "Fix automatically" sweep can never apply it. A machine deciding on a
reviewer's behalf that a question is fine is precisely the failure this row
exists to prevent. `mark_reviewed_broken` is offered alongside it for the
opposite call — parked as known-bad without being deleted.

Every verdict writes an `audit.log_event`, as the other bulk actions do.

### Migrations

`maths/0045_question_reports_and_review.py` — two new tables, no column added
to any existing one, so no lock risk on `maths_question` (~19,500 rows).
Forward-only.

### Permissions

- Reporting: any authenticated user, scoped to questions they can already see.
- Reviewing: superuser only, via the existing `SuperuserRequiredMixin` on the
  question-health pages. Unchanged gate, new action behind it.

### Not in scope

- Auto-closing the Jira issue when a report is cleared. The Jira item is the
  conversation with the reporter; the review row is the state of the bank.
- Reporting from the mixed quiz and worksheets. Same mechanism will fit; the
  topic quiz is where CPP-398 came from and where the traffic is.
