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
Auto-publish homework assignments that have reached their scheduled publish time.
```bash
python manage.py publish_scheduled_homework
```
Intended to run as a cron job (e.g. every 5 minutes).

---

## Maths & Quiz Data

### `backfill_final_answer_scores`
Backfill score and total_questions on StudentFinalAnswer records where total_questions is 0.
```bash
python manage.py backfill_final_answer_scores
```

### `consolidate_to_maths`
Migrate question/progress data from shared quiz and progress apps into the maths app.
```bash
python manage.py consolidate_to_maths            # apply
python manage.py consolidate_to_maths --dry-run  # preview
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
