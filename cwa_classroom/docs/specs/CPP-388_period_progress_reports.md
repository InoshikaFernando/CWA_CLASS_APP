# CPP-388 — Weekly / Monthly / Term progress reports

**Status:** implemented
**App:** `progress`
**Jira:** [CPP-388](https://codewizardsaotearoa.atlassian.net/browse/CPP-388)

A student's homework results already exist in the database, but nobody ever gets
told what they *mean*. The dashboards answer "how am I doing right now"; nothing
answers "how did this week go, and was it better than last week". This feature
closes each period — week, month, term — with a report the student and their
parents actually receive.

---

## 1. What a report is

A **period report** is a point-in-time snapshot of one student's homework and
worksheet performance over one closed period.

| Period    | Window                                | Generated                     |
|-----------|---------------------------------------|-------------------------------|
| `weekly`  | Monday → Sunday                       | Monday, for the week just ended |
| `monthly` | 1st → last day of month               | 1st, for the month just ended   |
| `term`    | `Term.start_date` → `Term.end_date`   | The day after a term ends       |

A period is only ever reported **once it has closed** — a half-finished week
would produce a number that changes under the reader, and a report the reader
cannot trust is worse than no report. Reports are immutable once generated: the
computed figures are frozen into `PeriodReport.data`, so the PDF a parent
downloads in December still says what the notification said in August.

### Cascading period resolution

Term boundaries come from the student's school (`classroom.Term`). Weekly and
monthly windows are calendar-based and school-independent, so an individual
student with no school still gets them. The fallback chain for "which school
does this student belong to" is:

1. the school on an active `ClassStudent` → `ClassRoom.school`,
2. else the student's `SchoolStudent` link,
3. else `None` — the student is an individual learner; weekly and monthly
   reports still generate, term reports do not (there is no term to close).

---

## 1a. Opt-in: nothing sends until a school switches it on

Reports notify families, so they are **off until configured**. Installing the
cron on a droplet must not start mailing every parent about a feature nobody
has seen.

Configuration cascades, most specific wins — the same shape as the fee cascade
in `classroom.fee_utils`:

    ProgressReportSetting(classroom=…)   a single class
    → ProgressReportSetting(department=…)
    → ProgressReportSetting(school=…)
    → off                                the hard default

So a school setting applies to the whole school, a department setting overrides
the school for that department's classes, and a class setting overrides both.

Each flag inherits **independently** (`NULL` = inherit), so a department can
switch weekly reports on without saying anything about term reports, and one
class can opt back out of what its department enabled.

| Flag | Meaning |
|------|---------|
| `weekly` / `monthly` / `term` | Which periods this scope reports |
| `notify_student` | In-app notification to the student |
| `notify_parents` | In-app notification to the linked parents |
| `email_parents_at_term` | The end-of-term parent email |

### Manual or automatic

Beyond *whether* a scope reports, it configures *when*:

| Mode | Behaviour |
|------|-----------|
| `manual` | **The default.** Nothing sends on its own; staff review and send from *Preview Reports* |
| `auto` | Sends on the configured day, unattended |

Manual is the default deliberately: a school should acquire a schedule by
choosing one, never by not noticing a setting.

Automatic timing is configured per scope and cascades like everything else:

| Field | Meaning | Default |
|-------|---------|---------|
| `send_weekly_on` | Day of week, 0 = Monday | Monday |
| `send_monthly_on` | Day of month, 1–28 (capped so February exists) | 1st |
| `send_term_after_days` | Days after the term ends | 1 |

The schedule decides **which day the school hears about it**, never what the
report covers — the window is always the closed one. `due_periods` therefore
offers every closed window on every run and lets the per-class schedule pick;
filtering there would hard-code Monday and the 1st for the whole install.

**One tick serves everyone.** A schedule that nothing reads never fires, so a
single daily cron still exists — but it is one generic entry for the install,
installed once, and no school configures anything at the OS level. The command
asks each class whether today is its day.

The delivery flags default to *on* once a scope generates anything, and to *off*
when it generates nothing — so switching weekly on does the obvious thing
without ticking three more boxes, and an unconfigured school stays silent.
Turning all three off gives a **silent trial**: reports generate and staff can
read them, and nothing reaches a family until the flags are switched on.
Nothing is stamped during a silent run, so a later switch still notifies.

**Scope follows configuration.** A report covers only the classes that switched
reporting on: a student in two classes where one reports gets a report about
that one, and `data['scope']` records which. That makes "only configured
classes get it" true of the contents, not just of the trigger.

### Preview and manual send

**Preview Reports** (`/progress/reports/preview/`) shows one row per student for
a chosen period and scope — the figures, the awards, and who each report would
reach — **computed live and saved nowhere**. A preview that wrote rows would
stamp delivery state and leave the real send with nothing to do, which would
make the word "preview" a lie.

The same page carries the *Generate and send* action, which is how a manual
scope sends at all. Manual sending ignores the schedule entirely: it is a
person saying "send it now".

Open to Head of Institute / institute owner / admin, plus HoD and teachers, who
can read what their classes would send without being able to switch reporting on.

Configured at **Report Automation** (`/progress/reports/settings/`), open to Head
of Institute / institute owner / admin. It is deliberately not a per-teacher
setting: switching it on starts notifying families.

The student and parent "My Reports" nav link is hidden until there is something
behind it — a report already generated, or a class configured to generate one.

---

## 2. What is in a report

All figures derive from **homework submissions** (`homework.HomeworkSubmission`)
in the window, with worksheets (`worksheets.WorksheetSubmission`) as a secondary
section. Nothing is invented: a period with no submissions produces a report
that says so rather than a report full of zeros dressed as achievement.

### 2.1 Headline figures (`data['totals']`)

| Figure | Meaning |
|--------|---------|
| `assigned` / `completed` / `completion_pct` | Homework due in the window vs. attempted at least once |
| `submissions` | Total attempts made in the window (not distinct homework) |
| `avg_best_pct` | Mean of the student's **best** attempt per homework — the "what they can do" number |
| `avg_first_pct` | Mean of the student's **first** attempt per homework — the "what they could do cold" number |
| `improvement_pct` | `avg_best_pct − avg_first_pct`; the value retrying actually bought |
| `time_minutes` | Total time spent across attempts |
| `on_time_pct` | Share of homework whose first attempt landed before the due date |

`avg_first_pct` vs `avg_best_pct` is the pedagogically important pair, and the
reason the report exists in this shape: it makes practice visibly worth doing.

### 2.2 By topic (`data['topics']`)

Per `classroom.Topic`, resolved from the questions inside each submission
(`HomeworkStudentAnswer` → `maths.Question.topic`), an accuracy percentage over
every answer the student gave in the window. Rendered as a bar chart plus a
table. Answers whose question carries no topic are grouped under *Unclassified*
rather than dropped — a silently shrinking denominator is the kind of quiet
wrongness this codebase does not accept.

### 2.3 By attempts (`data['attempts']`)

One row per homework: attempts taken, first score, best score, gain. Plus a
distribution (how many homeworks were done once / twice / three or more times),
rendered as the pie chart. This is the section that exists to *motivate the
retry* — it shows effort converting into marks.

### 2.4 Trend (`data['trend']`)

Average best-attempt score bucketed by day (weekly reports) or by ISO week
(monthly and term reports), so a term report is a line the reader can follow
rather than 90 daily dots.

### 2.5 Recognition (`data['awards']`)

Awards are earned **against the student's classmates over the same window**, so
they mean something. A class with one active student awards nothing — a badge
for beating nobody is noise. Every award states its evidence in `detail` so a
parent can see why it was given.

| Code | Awarded to | Guard |
|------|-----------|-------|
| `top_scorer` | Highest `avg_best_pct` in the class | ≥ 2 active students with submissions |
| `hard_worker` | Most attempts in the class, having retried at least one homework | must have retried; ≥ 2 students |
| `most_improved` | Largest mean first→best gain | gain > 0; ≥ 2 students |
| `fast_and_accurate` | `avg_best_pct` ≥ 85 **and** lowest mean seconds per question | ≥ 2 students with timing data |
| `perfect_score` | Scored 100% on any homework in the window | none (individual) |
| `full_completion` | Attempted every homework due in the window | ≥ 2 homework due (individual) |

Ties award everyone tied — rationing recognition on a tiebreak the student
cannot see would be arbitrary.

---

## 3. Delivery

1. **In-app notification** to the student and to every linked parent
   (`classroom.ParentStudent`), for every period type, linking to the report.
   Notification email is deliberately suppressed here: a weekly email per child
   per week is how a school ends up in a spam folder.
2. **Email to parents at term end only**, and only when the term had activity —
   an email reading "0% average across 0 homework" lands as a system error
   rather than as news. Sent as `progress_report_term` via
   `classroom.email_service.send_templated_email`, template
   `email/transactional/term_progress_report.html`, carrying the headline
   figures, the awards, and a link to the full report.
3. **Graphical view** at `/progress/reports/<id>/` — Chart.js bar, pie and line
   charts fed from the frozen snapshot.
4. **Downloadable PDF** at `/progress/reports/<id>/pdf/` — rendered with
   ReportLab, including the same charts drawn server-side (`reportlab.graphics`),
   so the PDF is not a degraded copy of the web view.

### Who can see a report

`progress.access.can_view_report(user, report)`:

- the student themselves,
- a parent with an **active** `ParentStudent` link to them,
- a teacher who shares an active class with them,
- Head of Institute / institute owner of the report's school,
- superusers.

Anyone else gets a 404, not a 403 — a 403 confirms the report exists.

---

## 4. Generation

```bash
python manage.py generate_progress_reports              # every period due today
python manage.py generate_progress_reports --period weekly
python manage.py generate_progress_reports --date 2026-09-01 --dry-run
python manage.py generate_progress_reports --school wizards --classroom 42
```

`--school` (id or slug) and `--classroom` (id) narrow a run to one scope, which
is how you try a single class before switching anything on for real:

```bash
python manage.py generate_progress_reports \
  --period weekly --classroom 42 --dry-run
```

Run daily from cron; the command itself decides which periods actually closed on
the given date, so the schedule is one line rather than three:

```cron
10 6 * * * cd /home/cwa/CWA_CLASS_APP && venv/bin/python cwa_classroom/manage.py generate_progress_reports
```

**Idempotent.** Reports key on `(student, period_type, period_start)`; a re-run
finds the existing row and does not re-notify. `--force` recomputes an existing
report's data (leaving its notification state alone) for the case where a
grading fix landed after generation.

**Off is reported, not passed over.** A run where no class has that period
switched on says so — silence is indistinguishable from a broken cron.

**Never silently empty.** A student with no submissions in the window still gets
a report row so the absence is visible in the UI, but nothing is notified or
emailed for it — telling a child "here is your report: nothing" every Monday is
not motivating, and the school's own dashboards already surface non-submission.
The command prints counts for generated / skipped / notified.

---

## 5. Data model

`progress.PeriodReport`

| Field | Notes |
|-------|-------|
| `student`, `school`, `term` | `school`/`term` nullable (individual learners) |
| `period_type`, `period_start`, `period_end` | `unique_together (student, period_type, period_start)` |
| `data` | `JSONField` — the frozen snapshot described in §2 |
| `generated_at`, `notified_at`, `parent_emailed_at` | delivery state; null = not yet done |

`data` is the single source of truth for both the HTML view and the PDF, so the
two can never disagree. `data['scope']` records which classes the report covered,
so a reader asking "why is my other class missing?" can be answered from the
snapshot rather than from today's settings, which may since have changed.

`progress.ProgressReportSetting`

One row per configured scope, with partial unique constraints per level (NULL
never equals NULL in SQL, so a plain `unique_together` would allow duplicate
school rows and make the cascade non-deterministic). A row whose every flag is
`NULL` is deleted rather than kept, so the cascade never steps over a row that
says nothing.

---

## 6. Test coverage

- `progress/tests/test_report_settings.py` — the cascade: the off default, the
  manual default, each level overriding the one above, and flags inheriting
  independently.
- `progress/tests/test_preview_view.py` — who may preview, the figures shown,
  the manual send, and that previewing writes nothing.
- `progress/tests/test_settings_view.py` — who may configure it, the tri-state
  form, and the sidebar visibility rule.
- `progress/tests/test_periods.py` — window maths, including year boundaries.
- `progress/tests/test_report_builder.py` — totals, topics, attempts, trend.
- `progress/tests/test_awards.py` — every award rule and its guard.
- `progress/tests/test_generate_command.py` — idempotency, notification and
  term-email behaviour, `--dry-run`, `--force`.
- `progress/tests/test_views.py` — access control for each role, PDF response.
- `progress/tests/test_pdf.py` — the PDF renders and is a real PDF.
- `ui_tests/progress/test_period_report_ui.py` — student and parent see the
  report page, charts mount, PDF link is present.
- `ui_tests/progress/test_report_settings_ui.py` — the settings page, the
  cascade badges, and the hidden-until-configured nav link.
