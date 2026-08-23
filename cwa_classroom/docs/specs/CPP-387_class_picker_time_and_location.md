# CPP-387: Class selection must list the location and time

## Problem

Every place a student is put into a class listed classes by **name** (plus, in
some places, subject and department) and nothing else:

- `templates/admin_dashboard/school_students.html` — the **Add Student** modal's
  "Assign to Classes" checkbox list.
- `templates/admin_dashboard/add_parent.html` — the inline student created on
  the **Add Parent** page.
- `templates/admin_dashboard/partials/student_edit_modal.html` — the **Classes**
  section of the student edit modal.
- `templates/teacher/class_detail.html` — the **Move to…** dropdown that moves a
  student from one class into another.

An institute typically runs the same class several times a week — *Year 10
Maths* on Tuesday afternoon at the Hamilton campus and *Year 10 Maths* on
Thursday morning at Rotorua. Those rows rendered **identically**, so whoever was
adding the student picked one at random and the mistake only surfaced later, at
the register.

## Fix

Show, on every class row in those pickers, the two facts that tell same-named
classes apart: **when the class runs** and **where it is held**.

### 1. Two labels on `ClassRoom`

`classroom/models.py` gains two read-only properties, so every picker phrases
the same class the same way:

| Property | Built from | Example |
|----------|-----------|---------|
| `schedule_label` | `day`, `start_time`, `end_time` | `Tuesday 4:00 PM – 5:30 PM` |
| `venue_label` | `location`, `is_online` | `Hamilton Campus`, `Online`, `Hamilton Campus + Online` |

Each part is optional. A class with only a day reads `Tuesday`; one with only
times reads `4:00 PM – 5:30 PM`. Both properties return `''` when nothing is
set — the caller decides what to say instead, rather than the model inventing a
placeholder. `venue_label` reuses the CPP-371 `Location` and the hybrid
convention already established for class tiles in CPP-372.

A third property, `picker_label`, folds the same facts into one line for
`<option>` elements, which cannot hold markup:

```
Year 10 Maths — Tuesday 4:00 PM – 5:30 PM · Hamilton Campus
```

### 2. One shared picker partial

`templates/partials/class_picker_option.html` renders the label beside a class
checkbox: the class name, then department · subject, then a clock line
(`schedule_label`) and a map-pin line (`venue_label`). All three checkbox
pickers include it, so they cannot drift apart again.

### 3. Missing data is named, not hidden

A class with no schedule or no location renders a muted *"Time not set"* /
*"Location not set"* rather than an empty row. Two same-named classes that both
lack a venue still look alike, but the picker now says **why** — the class
record is incomplete — instead of silently rendering the ambiguity. Same in the
`Move to…` dropdown, via `picker_label`.

### 4. The move row wraps

The per-student action row on the class detail page (`Fee` / `Start date` /
`Progress` / `Reset Password` / `Move to…` / `Remove`) was a single un-wrapped
flex row. The longer dropdown label pushed `Move` and `Remove` past the edge of
their `<li>`, where the next row overlapped them and swallowed the click. The
row and its action column now wrap (`flex-wrap`), and the dropdown is a fixed
`w-40` so a long label truncates in the closed control instead of stretching the
row — the full label is still readable in the open dropdown, which is where the
class is actually chosen.

### 5. Ordering and queries

The class querysets behind these pickers now `select_related('location')` (no
N+1 on the new label) and order by `('name', 'start_time')`, so same-named
classes appear in time order rather than an arbitrary one.

Touched views: `SchoolStudentManageView` and `StudentEditModalView`
(`classroom/views_admin.py`), `AddParentView` (`classroom/views_parent_admin.py`),
and `ClassDetailView`'s `move_target_classes` (`classroom/views.py`).

## Out of scope

The student/parent-facing "browse and join a class" pages
(`accounts/select_classes.html`, `partials/global_class_card.html`) are a
different flow — a learner choosing for themselves, not staff assigning — and
are left unchanged.

## Tests

- `classroom/tests/test_cpp387_class_picker_labels.py` — the label properties
  across every combination of set/unset day, times, location and `is_online`;
  plus a rendering check per picker that two classes differing only by day and
  venue are distinguishable on the page.
- `ui_tests/classroom/test_cpp387_class_picker_ui.py` — Playwright: opens the
  Add Student modal on a school with two same-named classes, asserts each row
  carries its own time and location, that an unscheduled class says so, and that
  checking a row still enrols the student in exactly that class.
