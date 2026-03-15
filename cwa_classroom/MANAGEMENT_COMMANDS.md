# Management Commands

All custom Django management commands for the CWA Classroom project.

Run any command with:
```bash
python manage.py <command> [options]
```

---

## Setup & Seeding

### `setup_roles`
Create all standard roles and assign the admin role to superusers.

```bash
python manage.py setup_roles
```

### `setup_data`
Seed the database with roles, levels, subjects, topics, and packages. Use this for fresh deployments.

```bash
python manage.py setup_data
```

### `setup_dev`
Bootstrap a local dev database with roles, sample users, packages, levels, and topics. Creates test accounts you can log in with immediately.

```bash
python manage.py setup_dev
```

---

## Data Import

### `import_backup`
Import data from a CWA_CLASS_APP MySQL backup file into the current schema.

```bash
python manage.py import_backup <sql_file>
python manage.py import_backup <sql_file> --dry-run    # parse only, no writes
```

| Option      | Description                              |
|-------------|------------------------------------------|
| `sql_file`  | Path to the MySQL backup `.sql` file     |
| `--dry-run` | Parse and count rows without writing     |

### `import_maths_backup`
Import progress data from a `maths_*` schema MySQL backup.

```bash
python manage.py import_maths_backup <sql_file>
python manage.py import_maths_backup <sql_file> --dry-run
```

| Option      | Description                              |
|-------------|------------------------------------------|
| `sql_file`  | Path to the MySQL backup `.sql` file     |
| `--dry-run` | Parse and count rows without writing     |

---

## Data Migration

### `migrate_from_cwa_school`
Import maths data from the legacy CWA_SCHOOL MySQL database. Requires the `cwa_school_legacy` database alias to be configured in `settings.py`.

```bash
python manage.py migrate_from_cwa_school
python manage.py migrate_from_cwa_school --dry-run
python manage.py migrate_from_cwa_school --skip-users
```

| Option         | Description                                          |
|----------------|------------------------------------------------------|
| `--dry-run`    | Print what would be migrated without writing         |
| `--skip-users` | Skip user migration (if users already exist)         |

### `consolidate_to_maths`
Consolidate `quiz.Question/Answer` and `progress.*` data into the maths app.

```bash
python manage.py consolidate_to_maths
python manage.py consolidate_to_maths --dry-run
python manage.py consolidate_to_maths --skip-questions
python manage.py consolidate_to_maths --skip-progress
```

| Option             | Description                        |
|--------------------|------------------------------------|
| `--dry-run`        | Preview without writing            |
| `--skip-questions` | Skip question/answer migration     |
| `--skip-progress`  | Skip progress data migration       |

---

## Number Puzzles

### `generate_puzzles`
Pre-generate number puzzles and store them in the database. Puzzles are used by the Number Puzzles activity within Basic Facts.

```bash
python manage.py generate_puzzles --level 1 --count 500
python manage.py generate_puzzles --all --count 500
python manage.py generate_puzzles --all --count 500 --clear
python manage.py generate_puzzles --all --dry-run
```

| Option      | Description                                                                 |
|-------------|-----------------------------------------------------------------------------|
| `--level`   | Level number (1–6) to generate puzzles for                                  |
| `--all`     | Generate puzzles for all 6 levels                                           |
| `--count`   | Target number of puzzles per level (default: 500)                           |
| `--clear`   | Delete existing unreferenced puzzles before generating                      |
| `--dry-run` | Show expected counts without writing to the database                        |

> **Note:** Requires `NumberPuzzleLevel` fixtures to be loaded first. Levels 5–6 may produce fewer puzzles due to stricter mathematical constraints.

**First-time setup:**
```bash
python manage.py loaddata puzzle_levels
python manage.py generate_puzzles --all --count 500
```

---

## Maintenance

### `backfill_final_answer_scores`
Backfill `score` and `total_questions` on existing `StudentFinalAnswer` records that have `score=0` despite having quiz data. Matches by student + topic + level.

```bash
python manage.py backfill_final_answer_scores
```

### `reset_users_for_dev`
Reset all user passwords and emails for local/test environments. Run this after restoring a production or test database backup.

```bash
python manage.py reset_users_for_dev
python manage.py reset_users_for_dev --password MyPass123
python manage.py reset_users_for_dev --email test@example.com
python manage.py reset_users_for_dev --skip-email
```

| Option         | Description                                              |
|----------------|----------------------------------------------------------|
| `--password`   | Password to set for all users (default: `Password1!`)    |
| `--email`      | Email to set for all users (default: `inoshi.fernando@gmail.com`) |
| `--skip-email` | Only reset passwords, leave emails unchanged             |

---

## Cleanup

### `clear_staff`
Remove all staff/teacher users and their related records (SchoolTeacher, DepartmentTeacher, Schools). Protects admin and superuser accounts.

```bash
python manage.py clear_staff                        # dry-run (shows what would be deleted)
python manage.py clear_staff --confirm              # actually delete
python manage.py clear_staff --confirm --keep-schools  # delete users but keep schools
```

| Option           | Description                                              |
|------------------|----------------------------------------------------------|
| `--confirm`      | Actually delete (without this flag, only shows dry-run)  |
| `--keep-schools` | Keep School records, only delete users and memberships   |
