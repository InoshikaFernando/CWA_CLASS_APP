# CPP-395 — One progress report per student, per subject, per period

Status: **draft** · Supersedes the split between `classroom.ProgressReport` and
`progress.PeriodReport` · Depends on CPP-388

> **Hosting note.** This spec assumes the DigitalOcean stack (Caddy → gunicorn →
> Django, DO Managed MySQL, Redis, Spaces). The app was migrated off
> PythonAnywhere; any PythonAnywhere instruction in older specs is stale. See
> `Runbooks/production-deployment.md`.

## 1. Overview

A student who takes Maths, Coding and Science gets **one** progress report that
mixes all three, and it reports maths practice against a coding class. This
splits it: one report per student per subject per period, so a parent reads
"Coding, Term 2" and sees coding.

At the same time the app has **two** report artefacts with two sidebar entries —
a teacher-written rubric report and an automated activity report — covering the
same student and term. They merge into one artefact.

The merged report must **generate and send without any teacher input**. A
missing comment is a missing section, never a blocked report.

## 2. What exists today, and why it cannot express this

| Artefact | Model | Keyed by | Subject-aware? |
|---|---|---|---|
| Student Progress Report | `classroom.ProgressReport` | student, school, term, classroom | Indirectly — its criteria and comments are |
| Period Report | `progress.PeriodReport` | `(student, period_type, period_start)` | **No** |
| Teacher comment | `classroom.ProgressReportComment` | student, school, term, **subject** | Yes |
| Rubric criterion | `classroom.ProgressCriteria` | school, **subject** | Yes |

The load-bearing observation: **the rubric half is already per-subject.**
`ProgressReportComment.subject` and `ProgressCriteria.subject` are both real FKs.
Only `PeriodReport` lacks a subject, and its `unique_together` makes adding one
mandatory rather than optional — there is currently no way to store two reports
for one student in one week.

```python
# progress/models.py — the blocker
unique_together = ('student', 'period_type', 'period_start')
```

That tuple is also the daily cron's idempotency key. Widening it is therefore a
change to delivery safety, not just to a constraint, and §8 treats it as such.

## 3. User stories

- As a **parent**, I want one report per subject, so that "how is she doing at
  coding" is answered by a document about coding.
- As a **Head of Institute**, I want to choose what a report contains, so that
  reports go out on schedule even when teachers have not written comments.
- As a **teacher**, I want my rubric assessment and comment to appear inside the
  report the family actually receives, so that I am not writing into a second
  document nobody opens.
- As a **Head of Department**, I want my department's subject configured
  independently, so that Coding can report weekly while Maths reports per term.
- As a **student**, I want to see which subject a report is about before opening
  it, so that three notifications in one week are not three copies of the same
  thing.
- As an **admin**, I want historical reports reclassified rather than relabelled,
  so that last term's data is still true after the split.

## 4. Data model

### 4.1 `progress.PeriodReport` — add the subject, widen the key

```python
subject = models.ForeignKey(
    'classroom.Subject', on_delete=models.PROTECT,
    null=True, blank=True, related_name='period_reports',
    help_text='The subject this report covers. Null only on pre-CPP-395 rows '
              'that have not been split yet; see the backfill in §8.',
)

class Meta:
    unique_together = ('student', 'period_type', 'period_start', 'subject')
```

`PROTECT`, not `CASCADE`: deleting a Subject must not silently delete reports
families have already received.

**`NULL` is not "inherit" here** — it is "legacy, not yet split", and is the one
place in this spec where null is a state rather than an inheritance marker. MySQL
treats `NULL`s as distinct in a unique index, so a legacy row cannot collide with
a new one. The backfill drives the count of nulls to zero; a check command
reports any that remain rather than letting them sit unnoticed.

`data['scope']` gains `subject_slug` and `subject_name` so a stored snapshot
still says what it covered after settings change.

### 4.2 `progress.ProgressReportSetting` — a fourth field group

Content selection joins the existing cascade as `CONTENT_FIELDS`, each
`BooleanField(null=True)`, `NULL` = inherit:

| Field | Default once a period is on | Covers |
|---|---|---|
| `include_homework` | on | Homework assigned/completed, first vs best |
| `include_practice` | on | Quizzes, times tables, basic facts — maths only |
| `include_worksheets` | on | Worksheet completions |
| `include_topics` | on | Per-topic accuracy chart |
| `include_awards` | on | Class-relative recognition |
| `include_rubric` | on | `ProgressCriteria` assessment |
| `include_teacher_comment` | on | `ProgressReportComment` narrative |

The two manual sections default **on** but are never **required** — see §6.

### 4.3 Unchanged

`ProgressReportComment` and `ProgressCriteria` keep their shape. They are already
keyed the way this feature needs.

## 5. Resolution and inheritance

### 5.1 Configuration — unchanged cascade, one new axis

```
class row → department row → school row → off
```

Most specific wins, `NULL` inherits, an unset chain resolves to off for periods
and to the §4.2 defaults for content. Content fields inherit **independently**:
a department may switch `include_rubric` off without saying anything about
homework.

### 5.2 Which subject a report belongs to

```
Homework.subject_slug                        (the item's own subject)
  → ClassRoom.subject.slug                   (the class it was set in)
    → no subject: excluded from every per-subject report, and counted
      in a "unclassified work" figure the preview surfaces
```

Homework carries its own `subject_slug`, so a class is **not** a reliable proxy —
a maths worksheet set in a coding class belongs to the maths report. This is
already implemented for scoping (1.18.11) and is reused here rather than
re-derived.

### 5.3 Maths-domain strands

Quizzes, times tables and basic facts are maths and only maths. They appear when
the report's subject is Mathematics **and** `include_practice` resolves on. They
are never included in another subject's report, whatever the setting says — a
setting cannot make a times table part of a coding report.

## 6. Missing teacher input is a section, not a blocker

This is the rule the feature turns on, so it is stated as a rule rather than
left to the templates.

- A section that is configured **on** but has **no content** is **omitted**, not
  rendered empty. A "Teacher comment" heading over blank space reads as a
  teacher who had nothing to say.
- No configured-on section can prevent generation, notification or email.
  `generate_progress_reports` never blocks on a missing comment or an
  unassessed rubric.
- The report records what it actually contained in
  `data['sections_included']`, so a reader asking "why is there no comment"
  gets an answer from the snapshot rather than from today's settings.
- The preview names it explicitly per row — "no teacher comment" — so staff can
  choose to write one **before** sending, without that being the default and
  without it holding up the batch.

The inverse case is equally deliberate: a report with **no student activity at
all** still generates a row (existing CPP-388 behaviour) but still notifies
nobody, because `has_activity` gates delivery.

## 7. Views, URLs, templates, permissions

### 7.1 Merged surface

Three sidebar items become two:

| Today | After |
|---|---|
| Student Progress Report | *(removed — its content moves into the report page)* |
| Report Automation | Report Automation *(gains a Content tab)* |
| Preview Reports | Preview Reports *(gains a Subject column)* |

`classroom.ProgressReport` (the rubric artefact) is **retained as a model** for
history and is no longer separately generated. §9 covers what is not being done
to it.

### 7.2 Changes

| View | Change | HTMX |
|---|---|---|
| `progress:report_preview` | Subject column; one row per student **per subject**; "All classes" means one row per student per subject rather than one merged row | Partial on filter change |
| `progress:report_settings` | Content tab for the seven `CONTENT_FIELDS`, same cascade UI as the period flags | Partial per scope |
| `progress:period_report_detail` | Renders rubric + comment sections when present; names the subject in the heading | No |
| `progress:period_report_pdf` | Same sections as the page, from the same snapshot | No |

The preview's duplicate student names are **correct**, not a defect to hide:
Avisha appears three times because she has three subjects. The Subject column is
what makes the row unique, and the table sorts by student then subject so her
three rows sit together.

### 7.3 Permissions

Unchanged from CPP-388; no new rules, because a second report of the same kind
should not be a second permission model.

| Role | Preview | Configure | Read own/child |
|---|---|---|---|
| HoI | ✅ school | ✅ school | — |
| Institute owner / Admin | ✅ school | ✅ school | — |
| HoD | ✅ department | ❌ | — |
| Teacher | ✅ own classes | ❌ | — |
| Parent | ❌ | ❌ | ✅ own children |
| Student | ❌ | ❌ | ✅ self |

Configuration stays HoI-and-above: switching reporting on starts notifying
families, which is not a per-teacher decision.

## 8. Migration and rollout

Three migrations, deliberately separated so each can be verified before the next.

**M1 — schema.** Add `subject`, widen `unique_together`. Nullable, so it applies
to production without touching a row.

**M2 — backfill, as a management command, not a migration.**
`split_period_reports [--dry-run] [--school] [--period]`. Recomputes rather than
relabels, per the requirement that old data be *correctly* classified:

1. For each legacy row, determine the subjects its window actually covered.
2. Rebuild one report per subject over the same window via `build_report_data`.
3. **Carry the original `notified_at` / `parent_emailed_at` onto every child
   row.** Non-negotiable: without it, splitting one sent report into three
   re-notifies a family about a period they already heard about.
4. Retain the legacy row with `subject=NULL`, marked superseded — nothing a
   parent has already opened disappears or changes.

**Recomputation can disagree with the frozen snapshot.** `PeriodReport.data` was
frozen precisely so a PDF downloaded months later still says what the
notification said; source data may since have changed (re-grading, deleted
homework). The command therefore **reports every figure that differs** and does
not silently overwrite. Run `--dry-run` on production and read the diff before
committing to it.

**M3 — cleanup.** Only once M2 reports zero unsplit rows: make `subject`
non-nullable. A separate release, so a bad backfill is recoverable by re-running
M2 rather than by a schema rollback.

**Rollback.** M1 and M2 are independently reversible: drop the widened
constraint, delete rows with a non-null subject, and the legacy rows are
untouched and still authoritative.

**Cron.** Unchanged: `generate_progress_reports` still runs daily, now looping
subjects within each class. The drop-in at `/etc/cron.d/cwa-progress-reports`
**is still not installed on either droplet** — automatic mode does nothing until
it is, independently of this ticket.

## 9. Out of scope

- **Deleting `classroom.ProgressReport`.** History stays readable. Retiring the
  model is a later ticket once nothing reads it.
- **Rewriting rubric assessment.** `ProgressCriteria` keeps its shape and its
  own editing UI.
- **Per-subject *scheduling*.** All subjects in a class share its period
  schedule. Splitting that is a follow-up if a school asks.
- **Non-maths practice strands.** There is no coding equivalent of times tables
  yet; when one exists it registers through the subject plugin.
- **Rubric freshness on short periods.** A weekly report shows the term's rubric
  read-only with its assessment date. Making rubric assessment weekly is not
  proposed.
- **Fixing "Unclassified" topics.** Tracked separately below — it is a registry
  change, not a reporting one, and this spec does not depend on it.

## 10. Sprint breakdown

### Sprint 1 — subject-correct content *(1.18.11, shipped)*
- CPP-395a ✅ Scope the report's strands by subject; stop maths practice
  appearing in a coding report.

### Sprint 2 — the subject key
- CPP-XXX M1: `subject` FK and widened `unique_together`.
- CPP-XXX Generate one report per subject; record subject in `data['scope']`.
- CPP-XXX Preview: Subject column, one row per student per subject, "All
  classes" fans out.
- CPP-XXX Notifications name the subject.
- CPP-XXX `topics_section` resolves per-subject topic names via a new
  `SubjectPlugin.content_topic_names()` — ends "Unclassified" for coding.

### Sprint 3 — the merge
- CPP-XXX Rubric + comment sections render inside the period report.
- CPP-XXX `CONTENT_FIELDS` cascade and the Report Automation Content tab.
- CPP-XXX Omit-when-empty for every manual section; `data['sections_included']`.
- CPP-XXX Preview flags "no teacher comment" without blocking the batch.
- CPP-XXX Remove the Student Progress Report sidebar entry.

### Sprint 4 — history
- CPP-XXX `split_period_reports` with `--dry-run` and a difference report.
- CPP-XXX Delivery-timestamp carry-over, with a test proving no re-notification.
- CPP-XXX Production dry run; read the diff.
- CPP-XXX M3: `subject` non-nullable.

## 11. Edge cases

| Case | Behaviour |
|---|---|
| Student in two classes of the same subject | **One** report covering both. Two coding classes must not mean two coding reports. |
| Class with no subject set | Its work joins no per-subject report; the preview names the count so it is visible rather than silently dropped. |
| Student at two institutes | Already school-scoped (1.18.2/1.18.4). Subject splits **within** a school; the school scope still wins. |
| Subject deleted | `PROTECT` refuses while reports exist. |
| Parent with several children | Unchanged; one notification per child per subject, which is the point. |
| Teacher writes a comment after sending | Appears on the page; no re-send. The snapshot records what was sent. |
| Term report with no term | Existing CPP-388 behaviour: no window, nothing generated. |
| Backfill run twice | Idempotent on the widened key; the second run reports zero to split. |
| Content section switched off after sending | The stored snapshot is unchanged. `data['sections_included']` is what the page trusts, not today's settings. |

## 12. Tests

Per repo convention, each app's suite lives in `<app>/tests/` and every UI test
inside a group package under `ui_tests/<group>/` — a file at the `ui_tests/`
root belongs to no CI job and never runs (`tests_workflows.py` fails the build
if that happens).

**Unit** — subject scoping (done, `progress/tests/test_subject_scope.py`); the
widened key admitting two same-week reports; one report for two classes of one
subject; content cascade resolution; omit-when-empty; **generation succeeding
with no teacher comment**; backfill carrying delivery timestamps; backfill
idempotency; snapshot honoured over changed settings.

**UI (`ui_tests/progress/`)** — preview shows one row per student per subject;
duplicate names with distinct subjects; Content tab cascade; a report page with
no comment shows no empty comment section.
