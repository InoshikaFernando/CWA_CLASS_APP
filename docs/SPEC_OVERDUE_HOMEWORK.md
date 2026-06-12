# Overdue Homework — Per-Student — Spec

**Epic:** Homework (CPP-74)

## What & Why

Today an overdue homework is effectively dead: the student is hard-blocked from
opening it once the due date passes (*"This homework is past its due date."*).
Teachers and students want overdue work to stay completable — a missed deadline
should be recorded, not slammed shut.

There is also a fairness gap: a student who joins a class **after** a homework's
due date currently gets the same "overdue/closed" treatment for work that was
never theirs to do on time. They should see it as a normal, optional assignment
— never flagged as overdue — while still being free to attempt it.

## Core idea

"Overdue" stops being a property of the homework alone and becomes **relative to
the student**, anchored on `ClassStudent.joined_at`:

> A homework is **overdue _for a student_** only when it is past due **and** the
> student was enrolled on or before the due date. A student who joined after the
> due date never sees it as overdue — for them it is just an available
> assignment.

## Behaviour

| Actor | Situation | Before | After |
|-------|-----------|--------|-------|
| Student (enrolled before due) | Past-due homework, no submission | Blocked, "Closed" | "Overdue" badge, **can still attempt** |
| Student (enrolled before due) | Submits after due | "Late Submission" | "Overdue Submission" |
| Student (joined after due) | Past-due homework | "Closed"/overdue | Normal "Pending", attemptable, **not** flagged overdue |
| Teacher | Student submitted late (enrolled before due) | "Late" | "Overdue Submission" |
| Teacher | Student missed it (enrolled before due) | "Overdue" | "Overdue" (unchanged) |
| Teacher | Late joiner, no submission | "Overdue" | "Pending" (blameless) |

## Scope

- No new models, **no migrations** — `ClassStudent.joined_at` already exists.
- Model helpers in `homework/models.py`:
  - `Homework.is_overdue_for(joined_at)` — per-student overdue test.
  - `HomeworkSubmission.submission_status_for(joined_at)` — lateness that ignores
    pre-join deadlines (existing `submission_status` property kept intact).
- View changes in `homework/views.py`:
  - `StudentHomeworkTakeView.get` — removed the `is_past_due` hard block; only the
    attempt cap gates access.
  - `StudentHomeworkListView` — `can_attempt` is now attempts-only; per-row
    `status`/`is_overdue` computed from the student's join date.
  - `HomeworkDetailView` (teacher) — per-student status uses each row's
    `ClassStudent.joined_at`.
- Templates:
  - `student_list.html` — "Overdue" badge + active action button; "Overdue
    Submission" label; due-date line no longer says "Closed".
  - `teacher_detail.html` — late submission labelled "Overdue Submission"; the
    homework-level badge reads "Past Due" instead of "Closed".

## Edge cases

- `joined_at is None` → treated as always-enrolled (falls back to clock-based
  overdue). Defensive only; real `ClassStudent` rows always set `joined_at`.
- Attempt cap still applies to overdue homework — exhausted attempts remove the
  action button regardless of due date.
- Teachers still cannot **create** homework with a past due date (unchanged form
  validation).

## Tests

- Unit (`homework/tests.py`): `HomeworkOverdueModelTest`, `LateJoinerOverdueTest`,
  plus updated take/detail/list assertions.
- UI (`ui_tests/test_homework.py`): `TestOverdueHomeworkUI` — overdue badge +
  action, take page opens, late joiner not flagged, teacher "Overdue Submission".
