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
Intended to run as a cron job every ~5 minutes. On the DigitalOcean server (`cwa` user):
```cron
*/5 * * * * cd /home/cwa/CWA_CLASS_APP && /home/cwa/CWA_CLASS_APP/venv/bin/python manage.py publish_scheduled_homework >> /var/log/cwa/publish_scheduled_homework.log 2>&1
```

---

## Progress Reports

### `generate_progress_reports`
Generate the weekly / monthly / term progress reports for any period that closed
on the given date, and deliver them: an in-app notification to the student and
their linked parents, plus — at term end only — an email to the parents. Reports
key on `(student, period_type, period_start)`, so re-running never duplicates a
report or re-notifies a family.

```bash
python manage.py generate_progress_reports                  # whatever closed today
python manage.py generate_progress_reports --period weekly  # the last closed week
python manage.py generate_progress_reports --date 2026-09-01 --dry-run
python manage.py generate_progress_reports --force          # recompute existing data
python manage.py generate_progress_reports --no-notify      # generate, send nothing
```

The command decides for itself which periods closed (weekly on Mondays, monthly
on the 1st, term the day after a `Term.end_date`), so it runs daily as one line.
A run on any other day is a legitimate no-op and says so. Installed by
`deploy/setup-app-prod.sh` as `/etc/cron.d/cwa-progress-reports`:

```cron
10 6 * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_generate_progress_reports.sh /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/progress_reports.log 2>&1
```

See [`docs/specs/CPP-388_period_progress_reports.md`](docs/specs/CPP-388_period_progress_reports.md).

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
