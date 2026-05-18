# Student Reports — Spec

**Jira:** CPP-294 | **Epic:** CPP-104 (Reporting & Analytics)

## What & Why

Admins (HoI/HoD/Owner) need a filterable student list report to manage their school's student body — seeing who is active, inactive, payment-blocked, or not enrolled in any class. This is the first entry in a new "Reports" left-nav section that will later house teacher, revenue, and expense reports.

## Scope

- New "Reports" collapsible sidebar section in `sidebar_hoi.html` and `sidebar_hod.html`
- `GET /reports/students/` — `StudentReportView` in `classroom/views_reports.py`
- Filters (query-string, bookmarkable): class, enrollment status, payment status, not-in-any-class
- HTMX partial table refresh with `hx-push-url="true"` for bookmarkable filtered URLs
- No new models, no migrations

## Roles & Scoping

| Role | Sees |
|------|------|
| HoI / Owner | All students in their school(s) |
| HoD | Only students enrolled in classes within their department(s) |
| Teacher / Student / Parent | 403 |

HoD scoping uses the same pattern as `HoDReportsView` (classroom/views.py:3532).

## URL Routes

```
GET /reports/students/          → StudentReportView      (name: reports_students)
```

Added to `classroom/urls.py`.

## Filters

| Param | Values | Behaviour |
|-------|--------|-----------|
| `class_id` | int | Filter to students in this class |
| `status` | `active`, `inactive`, `all` | Filter by `SchoolStudent.is_active` (default: `all`) |
| `payment` | `blocked`, `ok`, `all` | Filter by `CustomUser.is_blocked` (default: `all`) |
| `no_class` | `1` | Show only students with no active `ClassStudent` record |

## Data Model (read-only, no new tables)

```
SchoolStudent → school (tenant FK), student (CustomUser), is_active
ClassStudent  → classroom, student, is_active
CustomUser    → is_blocked, blocked_reason
ClassRoom     → name, school, department, is_active
```

Key query:
```python
qs = SchoolStudent.objects.filter(school__in=school_ids).select_related('student').annotate(
    active_class_count=Count(
        'student__class_student_entries',
        filter=Q(student__class_student_entries__is_active=True,
                 student__class_student_entries__classroom__school__in=school_ids),
        distinct=True,
    )
)
```

## Template Structure

```
templates/
  reports/
    students.html               — page shell (filter bar + hx-target)
    _partials/
      student_report_table.html — HTMX partial (table body + pagination)
```

## Files Changed

| File | Change |
|------|--------|
| `classroom/views_reports.py` | New — `StudentReportView` + `ReportFilterForm` + HoD helper |
| `classroom/urls.py` | Add `/reports/students/` route |
| `templates/reports/students.html` | New page template |
| `templates/reports/_partials/student_report_table.html` | New HTMX partial |
| `templates/partials/sidebar_hoi.html` | Add Reports section |
| `templates/partials/sidebar_hod.html` | Add Reports section |
| `classroom/tests/test_views_reports.py` | Unit tests |
| `classroom/tests/test_e2e_student_report.py` | E2E tests |
