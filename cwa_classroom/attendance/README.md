# attendance

Class-session attendance tracking. Records when each class meets, who was present (students and teachers), and supports excused absences via tokens. The attendance UI lives under the classroom URL space (`/class/<id>/attendance/`) and is split into student-facing and teacher-facing views.

> **Status:** mid-refactor (CPP-64). The app code has been extracted from `classroom/`, but as of the current `settings.py` it is **not yet in `INSTALLED_APPS`** — the models are still owned by `classroom/` (migrations and `db_table` names preserve `classroom_*`). See the `PATCH_*.py` files in this directory for the cutover steps.

## Key models

- **ClassSession** — a single meeting of a class (date, start/end time, subject).
- **StudentAttendance** — student presence/absence per session.
- **TeacherAttendance** — teacher presence per session.
- **AbsenceToken** — vouchers used to excuse absences.

DB tables stay on `classroom_*` names through the refactor so no data migration is needed.

## URL prefix & key routes

Currently mounted under `classroom.urls` (no separate prefix); routes resolve to `/class/<class_id>/attendance/...` and similar paths.

## Integration (target state, post-cutover)

In `settings.py`:

```python
INSTALLED_APPS = [..., 'attendance', ...]   # not yet enabled
```

In root `urls.py` — included via `classroom.urls`; no top-level include needed.

## Cutover steps (from the original CPP-64 plan)

1. Add `attendance` to `INSTALLED_APPS`.
2. Apply the `PATCH_*.py` instructions in this directory.
3. `python manage.py migrate attendance`
4. `python manage.py makemigrations classroom --name remove_attendance_models`
5. `python manage.py migrate classroom --fake-initial`
6. Update test imports: `from attendance.models import ...`
7. `python manage.py test`

## Dependencies

- **classroom** — owns the existing migrations and DB tables; views are wired into `classroom.urls`.
- **accounts** — `CustomUser` is the student/teacher attendee.

## External services

None.
