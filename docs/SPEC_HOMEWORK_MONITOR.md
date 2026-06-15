# Homework Monitor — Class Filter — Spec

**Epic:** Homework
**Ticket:** CPP-344

## What & Why

The teacher Homework Monitor (`/homework/monitor/`) lists a teacher's homework
with a class selector. Previously the selector only listed individual classes
and defaulted to the first one, so a teacher with several classes had no way to
see everything at once, and returning from a homework's detail page always
dropped them back onto a single class.

This adds an **"All classes"** option that aggregates homework across every
class the teacher is assigned to, and makes the detail page's back button land
on that All view.

## Behaviour

- **Filter options:** `All classes` (value `all`) followed by each class the
  teacher teaches.
- **`?classroom=all`** — shows homework from every class the teacher teaches
  (`classroom__in` the teacher's classes), newest first. Each card is tagged
  with its class name so the teacher can tell them apart.
- **`?classroom=<id>`** — narrows to that one class (unchanged).
- **No param** — keeps auto-selecting the **first** class, so the "+ New
  Homework" shortcut (which needs a target class) stays available on first
  visit. All is opt-in via the dropdown or the back button.
- **Unknown / non-numeric id** — falls back to the first class; never 500s.
- **Back button:** the homework detail page breadcrumb links to
  `/homework/monitor/?classroom=all`, so returning always lands on the All view.
- **Empty states:** All view with no homework anywhere shows a neutral message;
  a single class with no homework keeps the "Create the first homework" link.

## Permissions

Unchanged — `teacher`, `senior_teacher`, `junior_teacher`. The All view is
scoped to the classes the requesting teacher is assigned to; other teachers'
classes never appear.

## Tests

- Unit: `homework/tests.py::TeacherHomeworkMonitorAllFilterTest` — All option
  present, cross-class aggregation, per-class narrowing, class badge, invalid /
  non-numeric id fallback, back-link target, other-teacher isolation.
- UI: `ui_tests/test_homework_monitor_all.py` — All option rendered, both
  classes' homework shown under All, class badge, and the detail back button
  landing on the All view.
