# classroom

The core of the platform. Owns the school hierarchy (School → Department → ClassRoom), the curriculum graph (Subject → Level → Topic → Question), the parent/student relationships, the public landing pages, and the admin dashboard. Most other apps either depend on `classroom` models or are mounted under URL routes defined here.

`classroom` also hosts the **subject registry** — a plugin hook (`classroom.subject_registry.register`) that subject apps (`maths`, `coding`, …) call from their `AppConfig.ready()` to advertise themselves to the hub, sidebars, and breadcrumbs.

## Key models

**Hierarchy**
- **School** — institute/tenant (trial dates, currency, subscription).
- **Department** — school division (subjects, staff).
- **ClassRoom** — student group (class_name, semester, department, subject).
- **ClassTeacher** / **DepartmentTeacher** — teacher assignment join tables.
- **Parent**, **StudentBalance** — parent linkage and account credit.

**Curriculum**
- **Subject** — curriculum subject (name, slug, school-scoped or global).
- **Level** — 1–8 = year levels, ≥100 = basic facts, ≥200 = custom.
- **Topic** — curriculum node under a subject (supports nested subtopics).
- **Question** — base question (question_type, difficulty, explanation, image/video).

**Attendance** (still owned here pending the `attendance` app cutover)
- **ClassSession**, **StudentAttendance**, **TeacherAttendance**, **AbsenceToken**.

**Invoicing**
- **Invoice**, **InvoiceLineItem** — one line per (invoice, classroom) covering session counts and rate.
- **InvoicePayment**, **CreditTransaction**, **PaymentReferenceMapping** — payment recording and credit ledger.
- **ClassStudent.billing_start_date** — first billable session date for a single enrollment. `NULL` = bill the full requested period (backdated data entry for a student who was already attending). Set to a date when the student genuinely starts mid-period — sessions before this date are skipped by the calculator.
- Gap-invoice logic in `invoicing_services.find_uncovered_date_ranges_by_classroom` is **per-classroom**: a classroom is treated as covered only if an issued invoice has a line item for that specific classroom. Adding a student to a new class after an invoice was issued for some other class does not silently drop the new class's sessions.
- **Resend** an issued invoice email via the **Resend** column on the invoice list (POST `/invoicing/<id>/resend/`, named `resend_invoice`). Sends to student + linked parents (`ParentStudent`) + guardians (`StudentGuardian`) using the same `email/transactional/invoice_issued.html` template the initial issue used. Use after correcting a bounced parent email — the invoice itself is not modified, only re-emailed. Drafts and cancelled invoices cannot be resent. Each resend writes an `invoice_resent` audit event with the recipient list.

**Reference / utility**
- **Currency** — ISO 4217 reference table.
- **EmailLog** — outgoing-email audit (used by `notifications` and the email service).

## URL prefix & key routes

Mounted at root (`path('', include('classroom.urls'))`). Public, hub, and email routes are defined directly in the project urlconf and **must come before** the classroom include.

- `/app-home/`, `/student-dashboard/`
- `/topics/`, `/topic/<id>/levels/`, `/level/<n>/`
- `/create-class/`, `/class/<id>/`
- `/admin-dashboard/`, `/admin-dashboard/schools/<id>/`
- `/admin-dashboard/manage-teachers/`, `/manage-students/`
- `/import-students/`, `/import-teachers/`, `/import-parents/` — CSV bulk import (preview + mapping)

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'classroom', ...]

TEMPLATES[0]['OPTIONS']['context_processors'] += [
    'classroom.context_processors.subject_apps',
    'classroom.context_processors.subject_sidebar_context',
    'classroom.context_processors.breadcrumbs_context',
]

MIDDLEWARE += [
    'cwa_classroom.middleware.MathsRoomRedirectMiddleware',
    'cwa_classroom.middleware.SubdomainURLRoutingMiddleware',  # subdomain → urlconf
]
```

`AppConfig.ready()` imports `classroom.signals` (auto-syncs Department membership when `ClassTeacher` rows change).

In root `urls.py` — order matters:

```python
# public + hub routes go FIRST
path('', PublicHomeView.as_view(), name='public_home'),
path('hub/', SubjectsHubView.as_view(), name='subjects_hub'),
# ...
path('', include('classroom.urls')),  # catch-all comes AFTER
```

## Subject registry plug-in hook

```python
# in your subject app's apps.py
from classroom.subject_registry import register
from .plugin import MyPlugin
register(MyPlugin())
```

`maths` and `coding` use this to appear in the subjects hub and sidebar.

## Dependencies

- **accounts** — every actor is a `CustomUser`.
- **billing** — `School.subscription`, plan-limit checks, currency.

## External services

None directly, but views call into `billing.entitlements` for access control and `audit.services.log_event` for audit-relevant actions.
