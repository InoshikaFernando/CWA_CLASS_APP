# Management Commands Reference

## Setup & Development

### `setup_roles`
Creates all standard Role records, assigns 'admin' to superusers, and backfills UserRole records.
```bash
python manage.py setup_roles
```

### `setup_dev`
Complete dev environment setup — creates roles, test users, packages, levels, subjects, and topics.
```bash
python manage.py setup_dev
```

### `setup_data`
Seeds database with roles, year levels 1-8, basic facts levels 100-132, subjects, topics, and packages.
```bash
python manage.py setup_data
```

### `reset_users_for_dev`
Reset all user passwords and emails for local/test environments.
```bash
python manage.py reset_users_for_dev                    # default password: Password1!
python manage.py reset_users_for_dev --password MyPass1
```

---

## School Management

### `clean_school`
Wipe all imported data for a school (students, teachers, classes, departments, guardians).
```bash
python manage.py clean_school                                  # dry-run (shows counts)
python manage.py clean_school --confirm                        # wipe data, keep School record
python manage.py clean_school --delete --confirm               # cascade delete School + all data
python manage.py clean_school --school 3 --confirm             # target by ID
python manage.py clean_school --name "Sipsetha" --delete --confirm  # target by name
python manage.py clean_school --keep-users --confirm           # delete data but keep user accounts
```

| Flag | Effect |
|------|--------|
| *(no flags)* | Dry-run — shows counts, deletes nothing |
| `--confirm` | Actually delete |
| `--delete` | Also delete the School record itself (cascade) |
| `--school <id>` | Target school by ID |
| `--name <text>` | Target by name (case-insensitive partial match) |
| `--keep-users` | Delete school data but preserve user accounts |

### `clear_import_data`
Delete all imported data (students, teachers, parents, classes, departments) for a school or all schools.
```bash
python manage.py clear_import_data                       # dry-run
python manage.py clear_import_data --school "name"       # filter by school
python manage.py clear_import_data --confirm             # actually delete
python manage.py clear_import_data --nuke --confirm      # also delete schools + orphan users
```

### `clear_staff`
Remove all staff users and their related records.
```bash
python manage.py clear_staff                # dry-run
python manage.py clear_staff --confirm      # actually delete
```

---

## Billing & Subscriptions

### `sync_stripe_prices`
Sync Stripe Price IDs into InstitutePlan and Package records by matching price amounts.
```bash
python manage.py sync_stripe_prices            # apply
python manage.py sync_stripe_prices --dry-run  # preview only
```

### `backfill_subscriptions`
Create SchoolSubscription records for schools that existed before the billing system.
```bash
python manage.py backfill_subscriptions            # apply
python manage.py backfill_subscriptions --dry-run  # preview
```

### `grant_free_access`
Grant free (permanently active) subscriptions to students and schools with no active subscription.
```bash
python manage.py grant_free_access            # apply
python manage.py grant_free_access --dry-run  # preview
```

### `student_modules`
Put individual students on a per-student module, or take them off one. Student
Basic (the free promotional edition, without the AI-graded questions) is granted
here or in the Django admin and nowhere else — there is no student-facing route
onto it.
```bash
python manage.py student_modules --list
python manage.py student_modules --grant basic --user ada --user grace
python manage.py student_modules --grant basic --file cohort.txt --dry-run
python manage.py student_modules --grant ai_grading --user ada   # sell it back
python manage.py student_modules --revoke basic --user ada
```

### `free_trial_code`
Mint the code that gives a cohort a fixed, free, card-free run of the app — the
MHM promotion. Sets the three fields that have to agree and each fail quietly on
their own: 100% off (so Stripe is never reached and no card is asked for),
`grant_days` (so the access actually ends), and `grants_student_basic` (so the
AI-graded questions are left out). When the window closes the student is walled
and asked to subscribe; paying revokes Student Basic and hands them the
AI-graded questions automatically.

Re-running updates the code in place. It cannot add the Student Basic tier to a
code students already hold — that would change what those students get the next
time their subscription is activated — and says so rather than doing it.
The same code can be built in the admin UI: **Billing → Coupon Codes → Create**,
target **Student (Billing)**, 100% off, tick *Student Basic*, and set *Access
Duration* to 14. The command stays for scripted or bulk setup, and for the
`--deactivate` switch.

```bash
python manage.py free_trial_code --code MHM2WEEKS --dry-run
python manage.py free_trial_code --code MHM2WEEKS --max-uses 200
python manage.py free_trial_code --code MHM-TERM4 --days 21 --expires 2026-12-19
python manage.py free_trial_code --code MHM2WEEKS --deactivate  # stop new sign-ups
```

### `notify_payment_required`
Email families who are not paying, with the discount code and a link to start.
Two audiences, because the lists are not the same people:

- `--audience regated` (default) — students the re-gating pass put back behind
  the payment wall who have logged in before. Run after
  `reset_imported_student_gating`.
- `--audience unsubscribed` — everybody with no live subscription of their own,
  **including students who never subscribed at all**. A student coming off a
  free promotion is invisible to `regated` (their profile is complete and they
  have logged in), so this is the audience a promotion goes to.

`--include-parents` adds each student's linked parent or guardian — the student
has the account, the parent has the card. Anyone already emailed is skipped so
a re-run never double-sends; `--resend` overrides that. Always `--dry-run`
first: it prints the exact recipient list and sends nothing.
```bash
python manage.py notify_payment_required --school 4 \
    --audience unsubscribed --include-parents --dry-run
python manage.py notify_payment_required --school 4 \
    --audience unsubscribed --include-parents \
    --discount-code MHM2WEEKS --discount-percent 100 \
    --link-url https://www.wizardslearninghub.co.nz/accounts/complete-profile/
```

### `promo_code_doctor`
Report whether each Student (Promo) code has actually taken effect for anybody.
Read-only — it writes nothing, so it is safe against production. Separates a
counter with no members (never worked for anyone) from members the promo gave
nothing new to (worked, but was a no-op) from members whose class access exists
because of it.
```bash
python manage.py promo_code_doctor
python manage.py promo_code_doctor --code FULLACCESS2026
python manage.py promo_code_doctor --students   # name every redeemer
```

### `reset_invoice_counters`
Reset yearly invoice usage counters (for annual billing cycles).
```bash
python manage.py reset_invoice_counters            # apply
python manage.py reset_invoice_counters --dry-run  # preview
```

### `send_trial_expiry_warnings`
Send email warnings to schools/students whose trial expires within N days.
```bash
python manage.py send_trial_expiry_warnings              # default: 3 days
python manage.py send_trial_expiry_warnings --days 7     # 7 days warning
python manage.py send_trial_expiry_warnings --dry-run    # preview (don't send)
```

### `check_unpaid_access`
Daily paywall watchdog: cross-checks every delinquent subscription (past due /
cancelled / expired) against the page-hit log and reports any account that
reached a restricted page while unpaid. `TrialExpiryMiddleware` is the only
thing stopping that, and a regression in it does not error — the account simply
keeps working and nobody is billed.

Installed on PROD as `/etc/cron.d/cwa-unpaid-access` (daily 09:00, one-day
window, logs to `/var/log/cwa/unpaid_access.log`); the same signal is on the Ops
dashboard's **Subscription access** tile and in
`/api/health/?deep=1` under `warnings.unpaid_access`. Exits non-zero on a leak so
a cron wrapper can alert.
```bash
python manage.py check_unpaid_access                     # all delinquent users, 7-day window
python manage.py check_unpaid_access --days 30           # wider window
python manage.py check_unpaid_access --username Ovindik  # one account
python manage.py check_unpaid_access --quiet             # print only on a leak
python manage.py check_unpaid_access --webhook "$FEEDBACK_DISCORD_WEBHOOK"
```

---

## Classroom & Attendance

### `auto_complete_sessions`
Auto-complete expired class sessions (scheduled sessions past their end time).
```bash
python manage.py auto_complete_sessions
```
Intended to run as a cron job (e.g. every 15 minutes).

### `sync_department_teachers`
Ensure every teacher assigned to a class is also in that department.
```bash
python manage.py sync_department_teachers
```

### `backfill_department_levels`
Backfill DepartmentLevel M2M rows for departments created before the feature was added.
```bash
python manage.py backfill_department_levels            # apply
python manage.py backfill_department_levels --dry-run  # preview
```

---

## Homework

### `publish_scheduled_homework`
Auto-publish homework whose scheduled `publish_at` time has been reached. For each
due homework it sets `published_at` (making it visible to students/parents) and
notifies every active student in the class (in-app notification + email). Idempotent —
safe to re-run.
```bash
python manage.py publish_scheduled_homework
```
Runs every 5 minutes on both droplets, installed by `scripts/install_crons.sh`
as `/etc/cron.d/cwa-publish-homework` — you should not need to add it by hand:
```cron
*/5 * * * * cwa cd /home/cwa/CWA_CLASS_APP && venv/bin/python cwa_classroom/manage.py publish_scheduled_homework >> /var/log/cwa/publish_scheduled_homework.log 2>&1
```
Note the path: `manage.py` lives at `cwa_classroom/manage.py`, never at the repo
root. This entry previously ran `manage.py` from the root, so it failed on every
tick into its own log — and it had never been installed on production at all,
which meant no scheduled homework was ever published there.

The drop-in is written by `scripts/install_crons.sh`, and nothing in the deploy
path installs cron — so a droplet only gets it when someone runs that script
there (`--check` reports what is missing without writing). It previously lived
inside `deploy/setup-app-prod.sh`, which also upgrades the OS and overwrites the
Caddyfile, so nobody ran it and production went two weeks with no publish cron:
the question automation kept building sets and teachers published them by hand.
`homework/publish_health.py` now reports that state (a set past its `publish_at`
with no `published_at`) on the Ops dashboard and in `/api/health/?deep=1` under
`warnings.scheduled_publish`, so a missing cron is visible from the app itself.
Remedy: re-run `deploy/setup-app-prod.sh` as root — see
[`Runbooks/production-deployment.md`](../Runbooks/production-deployment.md) § 4.1.

### `generate_scheduled_questions`
Turn each due week of a teacher's question schedule (CPP-399) into a homework set.
A week is "due" once its release time minus the plan's `lead_days` has passed. The
homework is created with a **future** `publish_at`, so it stays invisible to
students until `publish_scheduled_homework` publishes it — that gap is the
teacher's preview window. Idempotent per week: a week that already produced a
homework is skipped, so a re-run or an overlapping manual run can never give a
class two sets for the same week.

A week whose planned topics yield no questions creates **nothing** and notifies the
class's teachers (in-app + email) instead of failing silently.

```bash
python manage.py generate_scheduled_questions
python manage.py generate_scheduled_questions --dry-run
python manage.py generate_scheduled_questions --schedule 12
python manage.py generate_scheduled_questions --dry-run --as-of 2026-09-07
```

| Flag | Effect |
|------|--------|
| `--dry-run` | Report what would be generated; write nothing |
| `--schedule <id>` | Limit to one `QuestionSchedule` |
| `--as-of YYYY-MM-DD` | Treat that date's end as "now" — rehearse a future run |

Runs daily on the DigitalOcean server via the drop-in installed by
`deploy/setup-app-prod.sh`; use the wrapper (it holds the flock) rather than
calling `manage.py` directly:
```cron
15 2 * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_generate_scheduled_questions.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/scheduled_questions.log 2>&1
```

---

## Progress Reports

### `generate_progress_reports`
Generate the weekly / monthly / term progress reports for any period that closed
on the given date, and deliver them: an in-app notification to the student and
their linked parents, plus — at term end only — an email to the parents. Reports
key on `(student, period_type, period_start)`, so re-running never duplicates a
report or re-notifies a family.

**Reports are opt-in and manual by default.** This command serves the classes
set to **automatic**, and only those whose configured day is today — so it is
one generic daily entry for the whole install, and no school configures
anything at the OS level. Classes left on manual wait for a staff member to
send them from *Preview Reports* (`/progress/reports/preview/`). Configure both
under *Report Automation* (`/progress/reports/settings/`).

On an install where nobody has configured anything, or on a day no schedule
lands, this generates nothing and says so — silence is indistinguishable from
a broken cron.

```bash
python manage.py generate_progress_reports                  # whatever closed today
python manage.py generate_progress_reports --period weekly  # the last closed week
python manage.py generate_progress_reports --date 2026-09-01 --dry-run
python manage.py generate_progress_reports --force          # recompute existing data
python manage.py generate_progress_reports --no-notify      # generate, send nothing
python manage.py generate_progress_reports --school wizards --classroom 42
python manage.py generate_progress_reports --manual --period weekly   # the manual classes
```

`--school` (id or slug) and `--classroom` (id) narrow the run, which is how you
try one class before switching anything on for real:

```bash
python manage.py generate_progress_reports --period weekly --classroom 42 --dry-run
```

The command decides for itself which periods closed (weekly on Mondays, monthly
on the 1st, term the day after a `Term.end_date`), so it runs daily as one line.
A run on any other day is a legitimate no-op and says so. Installed by
`deploy/setup-app-prod.sh` as `/etc/cron.d/cwa-progress-reports`:

```cron
10 6 * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_generate_progress_reports.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/progress_reports.log 2>&1
```

**Whole-school coverage (CPP-422).** A school can switch *Cover every student in
the school* on under *Report Automation*. The run then reaches every active
student of that school — including those in no reporting class and those with no
subscription — and the ones with nothing to show get one short email to their
parents saying why: no active subscription (with the sign-in link and the
school's discount code, when it has a valid one) or no work done in the period.
Off until switched on. One note per student per period, stamped in
`PeriodReportNotice`, so re-running the command re-mails nobody. The command
prints the cohort, the reason breakdown and any note that reached nobody:

```
weekly: Week of 07 Sep 2026 — Generated 12 report(s) for 12 student(s) across 3 class(es); ...
  whole school: 8 student(s) with nothing to show (5 no subscription, 3 no activity); 8 note(s) sent to 11 parent address(es)
```

`--dry-run` never builds report data, so it cannot know who was active; its
whole-school figure is reported as a floor ("at least N …"), not a total.
`--no-notify` silences the notes along with everything else.

See [`docs/specs/CPP-388_period_progress_reports.md`](docs/specs/CPP-388_period_progress_reports.md)
and [`docs/SPEC_REPORT_AUTOMATION_WHOLE_SCHOOL.md`](docs/SPEC_REPORT_AUTOMATION_WHOLE_SCHOOL.md).

---

## Maths & Quiz Data

### `backfill_final_answer_scores`
Backfill score and total_questions on StudentFinalAnswer records where total_questions is 0.
```bash
python manage.py backfill_final_answer_scores
```

### `backfill_partial_credit`
Give back the marks all-or-nothing grading took off past answers to questions
that ask for **more than one value** — a fill-in-the-blank sentence, a table of
values. A money chart with nine of ten cells right used to score zero; grading
was fixed forward (see `maths/partial_credit.py`), and this re-runs today's
grader over the payload each answer row already stores and awards the share the
student earned.

**One direction only** — a stored mark is never lowered, not a row's points and
not a submission's totals. Where a stored total is higher than its own rows
justify it is kept and the disagreement is reported.

Covers the two stores that keep both the raw payload and a per-answer points
field: auto-graded `homework.HomeworkStudentAnswer` and
`worksheets.WorksheetStudentAnswer` rows. **Quiz attempts are not backfilled**
— `StudentFinalAnswer` carries its own session id rather than the answers'
`attempt_id`, so an attempt's total cannot be recomputed from the answers under
it, and its saved review payload holds only the readable form of the answer.
The command counts and reports those rather than skipping them silently.

```bash
python manage.py backfill_partial_credit                       # dry run — report only
python manage.py backfill_partial_credit --source worksheets   # one store
python manage.py backfill_partial_credit --student 42
python manage.py backfill_partial_credit --question 4021
python manage.py backfill_partial_credit --limit 200           # smoke run
python manage.py backfill_partial_credit --apply               # actually write
```

Safe to re-run: an answer already worth what the grader says it is worth is
left alone, so a second run reports nothing.

### `consolidate_to_maths`
Migrate question/progress data from shared quiz and progress apps into the maths app.
```bash
python manage.py consolidate_to_maths            # apply
python manage.py consolidate_to_maths --dry-run  # preview
```

### `convert_fill_blanks`
Turn typed questions whose text carries `___` gaps into real fill-in-the-blank
questions — the sentence renders with an input in each gap instead of one box for
the whole thing. The underscores are the identifier. Writes `blank_spec` (the
accepted answers per gap, derived from the question's existing correct answer
rows) and sets `question_type='fill_blank'`; the answer rows themselves are left
alone, so the conversion is reversible and BrainBuzz/exports are unaffected.
Questions whose answers can't be mapped onto their gaps unambiguously are listed,
never guessed at.

This is the **backfill**. Questions arriving from now on are converted as they
are saved — the AI importer, the spreadsheet/ZIP upload and the teacher form all
route through the same `Question.apply_blank_format` entry point — so this
should find nothing after its first run.
```bash
python manage.py convert_fill_blanks                    # dry run — report only
python manage.py convert_fill_blanks --min-blanks 2     # only multi-gap sentences
python manage.py convert_fill_blanks --topic Statistics # one topic subtree
python manage.py convert_fill_blanks --level 10
python manage.py convert_fill_blanks --id 4021 --id 4022
python manage.py convert_fill_blanks --apply            # actually write
python manage.py convert_fill_blanks --revert --apply   # undo: clear the specs
```

### `fix_drawing_questions`
Re-grade bank questions whose answer is a **drawing the app cannot accept** —
"Draw a tree diagram to illustrate this situation", "Illustrate on a Venn diagram
the sets A and B", "Show this information on a bar graph". A student has no way to
draw in the app, so one of these left `ai_graded` hands them a text box and marks
them wrong however well they drew it on paper. Sets them to `human_graded`, which
hides them from quizzes and leaves them for a teacher to mark.

Uploads are already handled at their source (`worksheets.services` routes these at
classification time, and the upload preview sweeps sessions that predate that), so
this is only for what is already in the bank. It shares the upload path's predicate,
so the two can't drift apart on what counts as a drawing.

Questions the app *can* take a drawing for are never touched — `number_line`,
`plot_points`, `draw_on_grid`, `shape_select`, `table_of_values` and the rest all
render their own answer surface, as do MCQs with real options. Note `fill_blank`
is **not** exempt: it renders a sentence with an input at each gap, so a table
question saved under it has lost its table — `table_of_values` is the only type
that can take one.

Dry run by default, and exits non-zero while anything is outstanding, so a
scheduled run surfaces drift. Idempotent: `human_graded` questions are excluded
from the scan, so a rubric a teacher wrote is never re-read.
```bash
python manage.py fix_drawing_questions                  # dry run — report only
python manage.py fix_drawing_questions --apply          # actually write
python manage.py fix_drawing_questions --topic 75       # one topic
python manage.py fix_drawing_questions --level 7        # one year
python manage.py fix_drawing_questions --school 3       # one school's questions
python manage.py fix_drawing_questions --apply --quiet  # summary only
```

### `generate_puzzles`
Generate number puzzles and store them in the database.
```bash
python manage.py generate_puzzles --all              # all levels
python manage.py generate_puzzles --level 3          # specific level
python manage.py generate_puzzles --count 50         # how many
python manage.py generate_puzzles --clear            # remove existing first
python manage.py generate_puzzles --dry-run          # preview
```

### `regrade_typed_answers`
Give back the marks a grading defect took. Re-runs today's grader over the text
each student actually typed — `maths.StudentAnswer`, auto-graded
`homework.HomeworkStudentAnswer` and `worksheets.WorksheetStudentAnswer` — and
corrects the attempt scores, submission totals and topic/level statistics built
on them.

**One direction only** — wrong to right, never right to wrong. A mark already
awarded stays awarded; taking one back from a child months later, because
grading got stricter, is not a script's decision to make.

Covers the typed types graded by `Question.grade_text_answer`: short_answer /
fill_blank / calculation in the text / set / algebra / equation / pattern
formats, plus column_operation and long_division, which are worked out from the
question's own numbers. Choice questions, spec-graded geometry and AI- or
teacher-marked answers are left alone (see the command's docstring for why each).

```bash
python manage.py regrade_typed_answers                    # dry run — report only
python manage.py regrade_typed_answers --source quiz      # one store
python manage.py regrade_typed_answers --topic 147
python manage.py regrade_typed_answers --student 31
python manage.py regrade_typed_answers --question 4021
python manage.py regrade_typed_answers --limit 200        # smoke run
python manage.py regrade_typed_answers --apply            # actually write
```

The dry run prints every affected question, what each child typed, and each mark
before → after. Read it before applying. Safe to re-run: an answer already
marked right is left alone, so a second run reports nothing.

Runnable without an SSH session from **Actions → Re-mark past answers**, which
runs exactly this on a deployed site (`apply` unticked by default, `environment`
defaulting to test) and keeps the output on the run page — the record of who
gave the marks back, on which site, and what changed. It re-grades with the code
ON the droplet, so deploy the grading fix first or the run will honestly report
nothing owed.

### `relevel_questions`
Repair questions stranded at the wrong year, using the year of the **class** each
was actually assigned to.

Every upload path defaults `year_level` to 1, so a worksheet whose year the
extractor could not read files its whole batch at Year 1 — where level practice
(`_get_questions_for_level`, which filters on `level` alone) serves it to real
Year 1 students. The class a homework went to is set by a human before any AI
runs, so it is the signal this command trusts.

Prod carries two Level ladders with duplicate names: the curriculum one
(`level_number` 1–10) that questions are filed against, and the class one
(300+) that `ClassRoom.levels` points at. The command bridges them, resolving a
class level by `--map`, then built-in overrides, then a "Year N" reading of its
display name. Anything it cannot resolve — no homework link, an unrecognised
class level, or a tie between two years — is reported and left alone, never
guessed at. Classes above the ladder (VCE GM 1/2 and 3/4) are listed as
deliberately skipped rather than squashed into Year 10.

One vote per class, not per homework. Soft-deleted homework still counts as
evidence. Use `list_questions` first to see where a year's questions actually
sit.
```bash
python manage.py relevel_questions --year 1 --school 4 --dry-run   # preview
python manage.py relevel_questions --year 1 --school 4             # apply
python manage.py relevel_questions --year 1 --school 4 --map "JS=5"
python manage.py relevel_questions --year 1 --topic "Indices" --exact-topic
```

### `topic_doctor`
Report what is wrong with the topic tree, and fix the two things safely fixable.

Importers disagree about how they create topics. The AI import and the JSON
upload `get_or_create` a strand and a topic under it; the homework PDF path
matches on the bare name and, when nothing matches, files the question on
`Topic.objects.filter(subject=subject).first()` instead of creating anything.
That first row is a **strand**, and the student year page lists sub-topics only
— so the question is offered by no topic quiz and surfaces only in level
practice.

The report surfaces that (`TOP-LEVEL-HOLDS-QUESTIONS`, with the years those
questions sit at) alongside the findings from `classroom.topic_merge`:
duplicate names, empty topics, inactive topics still holding questions, parents
in another subject, and subjects sharing a name.

It deliberately does **not** guess which topics mean the same thing — fuzzy
matching ("Fraction" ≈ "Fractions") is wrong often enough to be dangerous and a
merge is not reversible. It states facts; a human picks the survivor.

`--keep`/`--absorb` re-points everything at the survivor (walking
`_meta.related_objects`, so a topic FK added by a later app is carried too),
re-parents the absorbed rows' sub-topics, then deletes them.
`--reparent`/`--under` moves one row — the fix for a parentless topic that
should sit under a strand; `--under 0` promotes a row to a strand. Both refuse
anything that would move questions out of their subject or make the tree three
levels deep, and both honour `--dry-run`.
```bash
python manage.py topic_doctor                          # full report (read-only)
python manage.py topic_doctor --subject mathematics    # one subject
python manage.py topic_doctor --only TOP-LEVEL-HOLDS-QUESTIONS
python manage.py topic_doctor --keep 207 --absorb 154 --dry-run
python manage.py topic_doctor --reparent 70 --under 4 --dry-run
```

---

## Jira Sprint Burndown

### `sync_sprint_burndown`
Record burndown snapshots (story points remaining) from Jira. It records a
**whole-project** snapshot — total points remaining across the project, which is
what the `/sprints/burndown/` chart shows — and, if a board is configured, the
**active-sprint** snapshot for per-sprint history. A burndown is time-series and
Jira only reports each issue's *current* state, so this must run on a schedule to
build up history. Idempotent — re-running upserts today's snapshot. The project
snapshot needs only `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` (and
`JIRA_PROJECT_KEY`, default `CPP`); the sprint snapshot additionally needs
`JIRA_BOARD_ID`. Override `JIRA_STORY_POINTS_FIELD` if your instance differs from
the `customfield_10016` default. View the chart at `/sprints/burndown/`.
```bash
python manage.py sync_sprint_burndown
```
Intended to run as a cron job 3x/day. Use the wrapper script
`scripts/cron_sync_sprint_burndown.sh` (loads the env file + venv, mirrors the
other cron scripts). A snapshot is upserted per (sprint, day), so multiple daily
runs just refresh that day's point — the last run wins for the date. On the
DigitalOcean server (`cwa` user):
```cron
# TEST app — 08:00, 14:00, 22:00
0 8,14,22 * * * /home/cwa/CWA_CLASS_APP_TEST/scripts/cron_sync_sprint_burndown.sh >> /var/log/cwa/sprint_burndown.log 2>&1
# PROD app (pass app dir + env file)
0 8,14,22 * * * /home/cwa/CWA_CLASS_APP/scripts/cron_sync_sprint_burndown.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/sprint_burndown.log 2>&1
```
The chart at `/sprints/burndown/` reads back the snapshots this command writes
and shows a "Last synced from Jira" timestamp from the most recent one.

---

## Data Import / Migration

### `import_backup`
Import mysqldump backup of CWA_CLASS_APP and map progress/quiz tables to maths models.
```bash
python manage.py import_backup path/to/backup.sql
```

### `import_maths_backup`
Import progress data from a backup already using maths table names.
```bash
python manage.py import_maths_backup path/to/backup.sql
```

### `import_prod_questions`
Import Question + Answer records from production dump, mapping old topic/level IDs.
```bash
python manage.py import_prod_questions            # apply
python manage.py import_prod_questions --dry-run  # preview
python manage.py import_prod_questions --overwrite  # replace existing
```

### `import_prod_progress`
Import StudentFinalAnswer quiz results from production dump.
```bash
python manage.py import_prod_progress            # apply
python manage.py import_prod_progress --dry-run  # preview
```

### `migrate_from_cwa_school`
One-time import of all maths data from legacy CWA_SCHOOL backup.
```bash
python manage.py migrate_from_cwa_school            # apply
python manage.py migrate_from_cwa_school --dry-run  # preview
python manage.py migrate_from_cwa_school --skip-users  # if users already exist
```
