# Runbook: CWA Classroom UI Smoketest

**Purpose:** End-to-end validation of the CWA Classroom app — login, sidebar
navigation, and **basic CRUD** across the core teacher/admin surfaces (Classes,
Students, Attendance, Question banks, Quizzes, Invoices) plus a student-facing
quiz run. This runbook is designed to be executed by an engineer or an AI agent
driving a **locally running dev server** (`python manage.py runserver`) through
a browser-automation MCP (`mcp__claude-in-chrome__*` preferred, `playwright`
MCP as a fallback).

**Philosophy:** If something doesn't work, **fix it.** Per the repo's
no-silent-failure rule — if a list silently renders `—`, a save swallows a 4xx,
or a quiz scores nothing — that is the bug, not the smoketest. Never edit the
database directly to make a step pass; trace the symptom from
template → view → model → DB, fix the correct layer, add or update a test,
commit, then resume.

---

## Completion Rules

These are non-negotiable. The smoketest is not complete until all are satisfied.

1. **Every numbered step must be attempted.** Do not skip a step because the UI
   "looks like" it doesn't support the action — open the row menu, scroll the
   detail page, switch the tab. If a step truly cannot be completed because the
   control is missing, that is a bug — log it, fix it, re-test.
2. **CRUD means CRUD.** If a step says "create, edit, delete" — test all three.
   "Page loads" alone is not a pass.
3. **Depth before breadth.** Finish each phase fully before moving on. Do not
   batch "does it load?" checks across pages.
4. **Console + server errors must be checked.** Read the browser console after
   login and after each Create/Edit/Delete (`mcp__claude-in-chrome__read_console_messages`),
   and watch the `runserver` stdout for tracebacks and `4xx`/`5xx` lines. Any
   uncaught JS exception, swallowed 4xx, 5xx, or Django traceback is a finding.
5. **Record a result for every numbered step** — PASS, FAIL (with bug
   details), or BLOCKED (with reason). Present a summary table at the end.
6. **Cleanup is mandatory.** Every `Smoke-*` record created here must be
   deleted before the runbook is marked complete (Phase 9). The smoketest
   leaves the database in the same logical state it found it in.
7. **All bugs found must be fixed and committed** before the smoketest is
   marked complete, per the Bug Handling Protocol below.

---

## Prerequisites

### 1. Browser automation MCP

```
Required:
  ✅ claude-in-chrome   — browser automation (preferred)
  — or —
  ✅ playwright         — fallback; adjust tool prefixes accordingly
```

If neither is available, you can still run the **scripted** smoke check
(`smoke_test.py`, see § Appendix A) but you will not be able to exercise CRUD —
note that as a partial run.

### 2. Python environment + database

The smoketest runs against SQLite by default — no MySQL required.

```bash
cd cwa_classroom
python -m venv ../venv && source ../venv/bin/activate   # if not already
pip install -r requirements.txt
```

`DB_ENGINE` defaults to `sqlite` (see `.env.example`). Leave it unset for a
file-backed dev DB. If you point at MySQL instead, set the `DB_*` vars first.

### 3. Seed roles, users and reference data

The dev seed creates roles, year levels, subjects, topics, packages, and a set
of known test users (see `cwa_classroom/MANAGEMENT_COMMANDS.md`):

```bash
python manage.py migrate
python manage.py setup_dev          # roles + test users + packages + levels + subjects + topics
python manage.py reset_users_for_dev   # sets every password to Password1!
```

`setup_dev` is idempotent — re-running it will not duplicate the seed.

### 4. Start the dev server

```bash
python manage.py runserver 0.0.0.0:8000
```

**Confirm it actually serves** before driving the browser — `runserver`
printing "Starting development server" is not the same as a healthy app:

```bash
curl -sS http://localhost:8000/api/health/
# Expected: 200, JSON body { "status": "ok", "version": "...", ... }
curl -sS "http://localhost:8000/api/health/?deep=1"
# Expected: 200 with a "checks" object — database/migrations/cache all "ok":true.
# A 503 "degraded" here tells you exactly which dependency is broken before you
# waste a smoketest run against it (e.g. unapplied migrations).
curl -sS -o /dev/null -w "login:%{http_code}\n"  http://localhost:8000/accounts/login/
# Expected: 200
```

If `/api/health/` is not 200, fix the stack before continuing — a smoketest
against a half-booted server proves nothing. Common causes: migrations not
applied (`django.db.utils.OperationalError: no such table`), or a missing
`SECRET_KEY`/`.env`.

### 5. Note the URLs and credentials

| Item | Value |
|------|-------|
| Base URL | `http://localhost:8000` |
| Login | `http://localhost:8000/accounts/login/` — username field is the **email** (`#id_username`), password `#id_password` |
| Health | `http://localhost:8000/api/health/` |
| Django admin | `http://localhost:8000/admin/` |
| Test password | `Password1!` (set by `reset_users_for_dev`) |
| Admin user | The superuser created by `setup_dev` (it prints the email). If none exists: `python manage.py createsuperuser` then `reset_users_for_dev`. |

> **Roles drive the landing page.** After login the app redirects by
> `ROLE_PRIORITY` (admin → institute_owner → head_of_institute →
> head_of_department → accountant → senior_teacher → teacher → junior_teacher →
> individual_student → student → parent). Do not assert on a fixed landing URL
> — instead navigate explicitly to the page each phase needs.

---

## Phase 1: Authentication & shell

### 1.1 Log in as an admin/teacher

1. Navigate to `http://localhost:8000/accounts/login/`.
2. **Expected:** the sign-in form renders (heading "Sign In").
3. Fill `#id_username` with the admin email, `#id_password` with `Password1!`,
   submit.
4. **Expected:** redirects off `/accounts/login/` into a dashboard
   (admin-dashboard, app-home, or student-dashboard depending on role).
5. If login returns to `/accounts/login/` with an error, the seed/password is
   wrong — re-run `reset_users_for_dev` and retry; record the divergence.

### 1.2 Verify the shell + read the console

1. Confirm the sidebar/nav renders with the destinations the role should see
   (Classes, Students, Attendance, Subjects, Billing/Invoices, etc.).
2. `mcp__claude-in-chrome__read_console_messages` — any red error, uncaught
   rejection, or `4xx/5xx` XHR is a finding.
3. Hit `http://localhost:8000/admin/` — **Expected:** Django admin loads (the
   admin user is staff).

---

## Phase 2: Classes (foundational)

Classes anchor students, attendance and progress, so create one first.

### 2.1 View classes

1. Navigate to the class list (`/class/progress/` or the "Classes" nav entry;
   `classroom/urls.py` `class_progress_list`).
2. **Expected:** the class list renders (may be empty on a fresh seed).

### 2.2 Create a class

1. Go to **Create class** (`/create-class/`, `create_class`).
2. Fill: Name `Smoke-Class-Alpha`, pick a subject/department, a schedule
   (day + time), and any required term.
3. Save.
4. **Expected:** redirect to the class detail page; the new class appears in
   the list with the right name and schedule.

### 2.3 Edit the class

1. Open `Smoke-Class-Alpha` → **Edit** (`/class/<id>/edit/`, `edit_class`).
2. Rename to `Smoke-Class-Alpha-Edited`; change the schedule time.
3. Save.
4. **Expected:** detail header + list reflect the new name/time after reload.

### 2.4 Create + delete a throwaway class

1. Create `Smoke-Class-Throwaway` (any subject/time).
2. Delete it (class detail/settings → delete, or the row action).
3. **Expected:** row removed; no console error; confirm dialog accepted if shown.

> **Keep** `Smoke-Class-Alpha-Edited` — Phases 3–6 use it.

---

## Phase 3: Students

### 3.1 View students

1. Open the class detail for `Smoke-Class-Alpha-Edited` → Students, or the
   admin "Manage students" surface.
2. **Expected:** the student list/table renders.

### 3.2 Create a student

1. Use **Bulk student registration** (`/bulk-student-registration/`,
   `bulk_student_registration`) or the single add control.
2. Add: First `Smoke`, Last `StudentOne`, year level, assign to
   `Smoke-Class-Alpha-Edited`.
3. Save.
4. **Expected:** the student appears in the class roster; a login credential /
   username is generated.

### 3.3 Edit the student

1. Open the student edit modal/page.
2. Change the year level or display name.
3. Save.
4. **Expected:** change persists across reload.

### 3.4 CSV import smoke (optional but recommended)

1. Go to **Import students** (`/import-students/`, `student_csv_upload`).
2. Upload a small CSV (use `generate_test_csvs.py` at the repo root to produce
   one, or `cwa_classroom/test_data/`).
3. Walk preview → map structure → confirm → credentials.
4. **Expected:** the preview parses, the mapping step lists columns, and the
   confirm step reports the rows it created. Any silently-dropped row is a
   finding.

> **Keep** `Smoke-StudentOne` for Phases 4–6.

---

## Phase 4: Attendance

### 4.1 Open attendance for the class

1. Class detail → **Attendance** (`/class/<id>/attendance/`,
   `class_attendance`).
2. **Expected:** the roster shows `Smoke-StudentOne` with attendance controls
   for the current session.

### 4.2 Mark + change attendance

1. Mark `Smoke-StudentOne` **Present**, save.
2. Re-open and change to **Absent** (or **Late**), save.
3. **Expected:** the state persists across reload; the change is reflected in
   any attendance summary/progress view.

---

## Phase 5: Question bank & Quiz authoring

The maths/coding subjects are driven by levels → topics → questions
(`classroom/urls.py` question routes, `quiz` app).

### 5.1 View the question list for a level

1. Navigate to a level's questions
   (`/level/<n>/questions/`, `question_list`).
2. **Expected:** the question list renders (possibly empty).

### 5.2 Create a question

1. **Add question** (`/level/<n>/add-question/`, `add_question` /
   `create_question`).
2. Fill a simple multiple-choice question: stem `Smoke-Q: 2 + 2 = ?`, options
   incl. a correct `4`, mark the answer, pick the topic.
3. Save.
4. **Expected:** the question appears in the level's list with the correct
   answer flagged.

### 5.3 Edit + delete a question

1. Edit `Smoke-Q` (`/question/<id>/edit/`, `edit_question`) — change the stem.
   Save; confirm it persists.
2. Create a throwaway question, then delete it
   (`/question/<id>/delete/`, `delete_question`).
3. **Expected:** edit persists; throwaway row removed.

> **Keep** `Smoke-Q` for Phase 6.

---

## Phase 6: Student quiz run (cross-cutting)

This proves the chain holds: a student logs in, takes a quiz containing the
question authored in Phase 5, and the score/progress records.

### 6.1 Log in as the student

1. Sign out the admin. Log in as `Smoke-StudentOne` (password `Password1!`).
2. **Expected:** lands on the student dashboard (`/student-dashboard/`).

### 6.2 Take the quiz

1. Navigate to the subject → level → topic → quiz that contains `Smoke-Q`.
2. Answer `Smoke-Q` correctly (`4`); submit the quiz.
3. **Expected:** the quiz scores the answer, shows a result, and the student's
   progress for that topic/level updates.

### 6.3 Verify progress recorded

1. Sign back in as admin → open `Smoke-StudentOne`'s progress
   (`progress` app views) or the class progress list.
2. **Expected:** the attempt from 6.2 is recorded with the correct score.
   A blank/zeroed progress despite a correct answer is a finding (trace the
   `quiz` → `progress` write path).

---

## Phase 7: Billing / Invoices (admin)

CWA's billing app generates invoices from attendance/fees (`billing` app, many
`ui_tests/test_invoice_*.py`).

### 7.1 View invoices

1. Navigate to the invoice list (Billing nav entry / `billing/urls.py`).
2. **Expected:** the invoice list renders.

### 7.2 Generate an invoice

1. Trigger invoice generation for the school/class (the "Generate" control, or
   `invoice_generation` flow).
2. **Expected:** an invoice is created for `Smoke-StudentOne`'s guardian/account
   with line items derived from fees/attendance.

### 7.3 Inspect + record a payment

1. Open the invoice detail; verify the balance and line items.
2. Record a manual payment (partial), save.
3. **Expected:** the balance decreases by the paid amount; the invoice status
   updates. A balance that doesn't move is a finding.

> If billing is not configured in your dev seed (no fees/packages), mark Phase 7
> **BLOCKED** with that reason rather than forcing it.

---

## Phase 8: Console / regression sweep

### 8.1 Browser console

```
mcp__claude-in-chrome__read_console_messages
```

Walk every line since the last clear. Red errors (uncaught exceptions, failed
XHR the UI swallowed, CORS), and noisy warnings that did not appear on a clean
page load are findings.

### 8.2 Server log scan

Scan the `runserver` stdout for the whole session. Look for tracebacks,
`500`/`403`/`404` lines that don't map to an intentional test step, and
`RuntimeWarning`/deprecation noise introduced by the change under test.

---

## Phase 9: Cleanup

Leave the database in its pre-test state. Delete in **reverse dependency
order** so each delete succeeds without an integrity error. A delete that
raises a `ProtectedError`/`IntegrityError` means the order is wrong or a
referencing row was missed — fix the order, do **not** force it with raw SQL.

1. **Invoices/payments** — void/delete `Smoke-StudentOne`'s invoice from
   Phase 7 (if created).
2. **Quiz attempts / progress** — these are usually owned by the student row
   and will cascade on student delete; verify after step 4.
3. **Questions** — delete `Smoke-Q` (Phase 5).
4. **Students** — delete `Smoke-StudentOne` (Phase 3).
5. **Class** — delete `Smoke-Class-Alpha-Edited` (Phase 2).
6. **Verify clean** — walk the class list, student list, and question list and
   confirm no `Smoke-*` record remains. Final console read should be quiet.

> Fast path for a throwaway dev DB: `python manage.py flush` wipes all data, or
> just delete the SQLite file and re-seed. Only do this on a disposable dev DB —
> never against MySQL/test data you want to keep.

---

## Bug Handling Protocol

When a bug is found:

1. **Document it.** Page, action, expected vs actual. Capture the console text
   + the server traceback.
2. **Investigate.** Browser console → network request → `runserver` traceback →
   the view/model in source.
3. **Find the layer.** Template/JS (UI swallowed a 4xx, rendered `—`), view
   (wrong queryset, missing `select_related`, silent `except`), or model/DB
   (constraint, migration drift).
4. **Fix at the source AND the silencer.** If a template rendered `—` for a
   missing-but-required field, fix both the dangling reference and the silent
   fallback.
5. **Add or update a test.** Put it in the right app's suite — the per-app
   layout under `cwa_classroom/<app>/tests/` and `ui_tests/` (Playwright). The
   command for that app is the one CI runs (see
   `github-ticket-implementation.md` § verification, or `.github/workflows/ci.yml`).
6. **Commit it.** Short, descriptive message.
7. **Resume.** Continue from the step where the bug was found.

### Common CWA bug patterns

| Symptom | Likely cause | Where to look |
|---------|--------------|---------------|
| Login submits, returns to `/accounts/login/` | Wrong password / user not seeded | Re-run `reset_users_for_dev`; check `setup_dev` output |
| `OperationalError: no such table` | Migrations not applied | `python manage.py migrate` |
| Page 500 with `RelatedObjectDoesNotExist` | View dereferences a null FK | The view's queryset + the template's `{{ obj.fk.field }}` |
| List renders `—`/blank rows | Silent fallback over missing data | The template tag / context that produced the placeholder |
| Static/CSS 404 (`/static/css/output.css`) | `collectstatic` not run / WhiteNoise misconfig | `python manage.py collectstatic`; `STATIC_*` in `settings.py` |
| Quiz scores 0 for a correct answer | answer-key mismatch or progress write skipped | `quiz` scoring → `progress` write path |
| Invoice balance doesn't move on payment | payment not linked / total recompute skipped | `billing` payment + invoice total recompute |
| CSV import drops rows silently | parse/validation error swallowed in preview | the `*CSVPreview`/`*CSVConfirm` view |
| 403 CSRF on POST | stale token / missing `CSRF_TRUSTED_ORIGINS` | `settings.py` `CSRF_TRUSTED_ORIGINS` |

---

## Appendix A: Scripted smoke check (no MCP)

`smoke_test.py` at the repo root drives a headless Playwright run against any
deployed environment — useful as a fast pre/post-deploy gate. It checks the
login page, logs in as a sanitised user, and asserts that key pages
(`/`, `/maths/`, `/coding/`, `/admin/`, static) return 2xx/3xx:

```bash
pip install playwright && playwright install chromium
python smoke_test.py http://localhost:8000
python smoke_test.py https://dev.wizardslearninghub.co.nz --headed --slow 300
```

It expects a user `user1@test.local` with password `Password1!` (present after
a sanitised DB refresh — see `test-env-db-refresh.md`). This is a **liveness**
check, not a CRUD smoketest; a green `smoke_test.py` does not substitute for the
phases above.

---

## Quick Reference

### Test data — full list

| Phase | Record | Survives until |
|-------|--------|----------------|
| 2.2 | `Smoke-Class-Alpha-Edited` | 9.5 |
| 3.2 | `Smoke-StudentOne` | 9.4 |
| 5.2 | `Smoke-Q` question | 9.3 |
| 7.2 | `Smoke-StudentOne` invoice | 9.1 |

### Surfaces exercised

| Phase | Path | View / app |
|-------|------|------------|
| 1 | `/accounts/login/`, `/admin/` | `accounts`, Django admin |
| 2 | `/create-class/`, `/class/<id>/edit/` | `classroom` |
| 3 | `/bulk-student-registration/`, `/import-students/` | `classroom` |
| 4 | `/class/<id>/attendance/` | `classroom` / `attendance` |
| 5 | `/level/<n>/add-question/`, `/question/<id>/edit/` | `classroom` / `quiz` |
| 6 | `/student-dashboard/`, subject quiz routes | `quiz`, `progress` |
| 7 | Billing / invoice routes | `billing` |

### Useful commands

```bash
python manage.py setup_dev            # seed roles/users/levels/subjects/topics
python manage.py reset_users_for_dev  # all passwords -> Password1!
python manage.py runserver 0.0.0.0:8000
python manage.py flush                 # wipe all rows (dev DB only)
curl -sS http://localhost:8000/api/health/   # liveness/version
```
