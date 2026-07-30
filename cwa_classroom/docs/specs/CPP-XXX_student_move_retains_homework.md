# CPP-XXX: Move a student between classes without losing their homework

## Problem

When a student is reassigned from one class to another, the app had no concept
of a *move* — only **add** (activate a `ClassStudent` row) and **remove**
(soft-deactivate it, `is_active=False`). A "move" was those two actions done by
hand.

Homework visibility keys off active enrolment: the student list
(`StudentHomeworkListView`) and the take/submit gate
(`_student_enrollment_redirect`) both require an `is_active=True` `ClassStudent`
row. So the moment a student was removed from their old class, that class's
homework vanished from their list and they could no longer open or submit it —
even though the intent was merely to reassign them, not to revoke work.

A moved student and a genuinely removed student (left the school, pulled for
non-payment, disciplinary) were **indistinguishable** in the data — both are an
inactive `ClassStudent` row — so "just keep homework visible for inactive rows"
would have handed removed students ongoing access to a class they no longer
belong to.

## Fix

Introduce a first-class **move** that is distinct from a **remove**, so homework
access can key off it without leaking access to removed students.

### 1. `ClassStudent.moved_at` (model)

A nullable, indexed `moved_at` timestamp. It is set **only** when the row is
deactivated via a Move; a plain Remove leaves it `None`. A
`has_homework_access` property expresses the rule:

```python
@property
def has_homework_access(self):
    return self.is_active or self.moved_at is not None
```

The move *destination* is recorded in the audit log (`class_student_moved`), not
as a second FK into `ClassRoom` — a second FK would clash with the `students`
`through` relation and the admin inline.

### 2. Homework access widened to retained moves

`StudentHomeworkListView` and `_student_enrollment_redirect` now treat a
membership as granting access when `is_active=True` **or** `moved_at` is set:

```python
ClassStudent.objects.filter(
    Q(is_active=True) | Q(moved_at__isnull=False),
    student=user,
)
```

This gives a moved student full access to the old class's homework — visible in
the list and attemptable/submittable (the take, submit and save-progress views
all gate through `_student_enrollment_redirect`). A plainly removed student
(`moved_at=None`) is unaffected and still sees nothing.

### 3. `ClassStudentMoveView` (action + UI)

New POST endpoint `class/<class_id>/student/<student_id>/move/`, same
role/scope as the remove view. It:

- activates (or creates) the target enrolment, clearing any stale `moved_at`;
- deactivates the source enrolment and stamps `moved_at = now`;
- retires the source `Enrollment` request (`approved` → `removed`);
- logs `class_student_moved`.

Source and target must be in the **same school** (a cross-school transfer would
leave the `SchoolStudent` link and billing inconsistent) and the target is
re-validated against the user's manageable classes. A "Move to…" class picker
sits beside the existing **Remove** control on the class detail page.

### 4. Revocation edge cases

`moved_at` is cleared (access revoked) whenever the retained state should end:

- **Re-enrolment** — the add-to-class flows clear `moved_at` when they
  reactivate a row (an active member is not "moved out"), including the move
  view's own target-activation and a move back to the original class.
- **Leaving the school** — `SchoolStudentRemoveView` deactivates active rows,
  but a moved-out row is already inactive, so it explicitly clears `moved_at`
  on the student's rows at that school. A student who leaves the school loses
  all retained access.

## Out of scope (v1)

A moved student can still *submit* the old class's homework, but the teacher's
homework **monitor/leaderboard** for that class lists the roster by
`is_active=True`, so a moved-out student won't appear there. Surfacing moved
students on the old class's monitor is deferred.

## Tests

- `homework/test_moved_student_homework.py` — moved student still sees and can
  open the old class's homework; a plain removal still revokes it; leaving the
  school revokes retained access.
- `classroom/tests/test_class_student_move.py` — move transfers the enrolment
  and retains the source; can't move to the same class or to an out-of-scope
  class; moving back clears the retained marker.
- `ui_tests/test_student_move.py` — admin performs a move on the class page and
  the student then sees the old class's homework in their list.
