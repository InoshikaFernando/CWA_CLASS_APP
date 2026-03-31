# Migration Plan: feature/school-management-system → Production

**Branch:** `feature/school-management-system`
**Date:** 2026-03-12
**50 commits ahead of `main`**

---

## 1. Migration Overview

### New Migrations (vs main)

| Order | App | Migration | Type | Data Backfill? | Description |
|-------|-----|-----------|------|----------------|-------------|
| 1 | classroom | `0033_classsession_progresscriteria_school_topiclevel_and_more` | Schema | No | Creates School, ClassSession, ProgressCriteria, TopicLevel, SchoolTeacher, ClassTeacher, TeacherAttendance, StudentAttendance, ProgressRecord models |
| 2 | classroom | `0034_rename_hod_to_hoi` | Schema | No | Updates SchoolTeacher role choices (HoD → HoI rename) |
| 3 | classroom | `0035_department_alter_schoolteacher_role_and_more` | Schema | No | Creates Department + DepartmentTeacher, re-adds HoD role, adds Classroom.department FK |
| 4 | classroom | `0036_studentattendance_approved_at_and_more` | Schema | No | Adds approved_at, approved_by, self_reported to StudentAttendance |
| 5 | classroom | `0037_schoolteacher_specialty` | Schema | No | Adds specialty field to SchoolTeacher |
| 6 | classroom | `0038_department_subject_and_question_school` | Schema | No | Adds subject FK to Department |
| 7 | classroom | `0039_add_day_time_description_to_classroom` | Schema | No | Adds day, start_time, end_time, description to Classroom |
| 8 | classroom | `0040_add_school_student_and_level_school_fk` | Schema | No | Creates SchoolStudent model, adds school FK to Level |
| 9 | classroom | `0041_add_created_by_to_classsession` | Schema | No | Adds created_by FK to ClassSession |
| 10 | classroom | `0042_progresscriteria_parent_and_more` | Schema | No | Adds parent self-FK to ProgressCriteria, unique constraint on ProgressRecord |
| 11 | maths | `0005_department_subject_and_question_school` | Schema | No | Adds school FK to maths Question (depends on classroom 0038) |
| 12 | maths | `0006_backfill_final_answer_scores` | **Data** | **YES** | Backfills score, total_questions, points from StudentAnswer records |
| 13 | maths | `0007_add_table_number_to_studentfinalanswer` | Schema + **Data** | **YES** | Adds table_number field + backfills from level.level_number |

### Cross-App Dependencies
- `maths 0005` depends on `classroom 0038` (needs School model for Question.school FK)
- Django handles ordering automatically via `dependencies` declarations

### Data Migrations to Watch
- **`maths 0006`** — Iterates all `StudentFinalAnswer` rows with score=0 to backfill from `StudentAnswer`. Could be **slow on large datasets** (row-by-row with related query per row).
- **`maths 0007`** — Iterates all times-table `StudentFinalAnswer` rows to copy `level.level_number → table_number`. Fast unless there are many thousands of times-table records.
- Both use `RunPython.noop` as reverse — **not reversible** without custom SQL.

---

## 2. Pre-Deployment Checklist

### Before deploying to TEST or PROD:

- [ ] **Backup the database**
  ```bash
  # MySQL dump
  mysqldump -u <user> -p <database_name> > backup_$(date +%Y%m%d_%H%M%S).sql

  # Or with gzip
  mysqldump -u <user> -p <database_name> | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz
  ```

- [ ] **Check current migration state**
  ```bash
  python manage.py showmigrations classroom maths
  ```
  Expected state on main:
  - `classroom`: up to `0032_merge_20260306_2205` ✅
  - `maths`: up to `0004_add_operation_to_studentfinalanswer` ✅

- [ ] **Estimate data migration time** (for maths 0006)
  ```sql
  -- Count rows that will be backfilled
  SELECT COUNT(*) FROM maths_studentfinalanswer WHERE score = 0 AND total_questions = 0;

  -- Count times-table rows for maths 0007
  SELECT COUNT(*) FROM maths_studentfinalanswer WHERE quiz_type = 'times_table' AND table_number IS NULL;
  ```

- [ ] **Notify users of potential downtime** (if data migration > 1000 rows, expect ~30s-2min)

- [ ] **Pull latest code**
  ```bash
  git fetch origin
  git checkout feature/school-management-system
  git pull origin feature/school-management-system
  ```

- [ ] **Install any new dependencies**
  ```bash
  pip install -r requirements.txt
  ```

---

## 3. Deployment Steps

### Step 1: Stop the Application
```bash
# Depending on your deployment method:
sudo systemctl stop gunicorn        # systemd
# or
sudo supervisorctl stop cwa_app     # supervisor
# or
pm2 stop cwa_app                    # PM2/node proxy
```

### Step 2: Pull Code
```bash
cd /path/to/cwa_classroom
git fetch origin
git checkout feature/school-management-system
git pull origin feature/school-management-system
```

### Step 3: Install Dependencies
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Step 4: Run Migrations (in order)
```bash
# Run all migrations at once — Django handles ordering via dependencies
python manage.py migrate

# Or if you prefer step-by-step with visibility:
python manage.py migrate classroom 0033  # Creates School, ClassSession, etc.
python manage.py migrate classroom 0034  # HoD → HoI rename
python manage.py migrate classroom 0035  # Creates Department
python manage.py migrate classroom 0036  # Attendance approval fields
python manage.py migrate classroom 0037  # SchoolTeacher specialty
python manage.py migrate classroom 0038  # Department.subject FK
python manage.py migrate maths 0005      # Question.school FK (depends on classroom 0038)
python manage.py migrate classroom 0039  # Classroom day/time fields
python manage.py migrate classroom 0040  # SchoolStudent + Level.school FK
python manage.py migrate classroom 0041  # ClassSession.created_by
python manage.py migrate classroom 0042  # ProgressCriteria tree + ProgressRecord unique

# DATA MIGRATIONS (may take time — monitor output)
python manage.py migrate maths 0006      # Backfill StudentFinalAnswer scores ⚠️
python manage.py migrate maths 0007      # Add table_number + backfill ⚠️
```

### Step 5: Collect Static Files
```bash
python manage.py collectstatic --noinput
```

### Step 6: Start the Application
```bash
sudo systemctl start gunicorn        # systemd
# or
sudo supervisorctl start cwa_app     # supervisor
```

---

## 4. Post-Deployment Verification

### 4a. Check Migration State
```bash
python manage.py showmigrations classroom maths
```
All migrations should show `[X]` (applied).

### 4b. Verify Data Backfills
```sql
-- Verify maths 0006: No more zero-score rows with actual answers
SELECT COUNT(*) FROM maths_studentfinalanswer
WHERE score = 0 AND total_questions = 0;
-- Should be 0 (or close to 0 — some may have genuinely 0 answers)

-- Verify maths 0007: All times-table rows have table_number set
SELECT COUNT(*) FROM maths_studentfinalanswer
WHERE quiz_type = 'times_table' AND table_number IS NULL AND level_id IS NOT NULL;
-- Should be 0
```

### 4c. Functional Smoke Tests

| Test | URL | Expected |
|------|-----|----------|
| Student dashboard loads | `/dashboard/` | Shows Year Level, Basic Facts, Times Tables, Recent Activity |
| Times tables 1-9 save | Complete any 1-9× quiz | Result appears in dashboard |
| Times tables 10-12 save | Complete a 10×, 11×, or 12× quiz | Result saves (table_number used, level FK can be null) |
| Basic Facts save | Complete a Basic Facts quiz | Result saves without errors |
| School management | `/schools/` (as HoI) | School details, departments, teachers visible |
| Session attendance | Create a session, mark attendance | Teacher attendance records created |
| HoD/HoI teacher attendance | Mark attendance as HoD/HoI | Can see/mark all class teachers |

---

## 5. Rollback Plan

### If something goes wrong BEFORE data migrations (0006/0007):

Schema migrations are safe to reverse:
```bash
# Roll back classroom to pre-feature state
python manage.py migrate classroom 0032

# Roll back maths to pre-feature state
python manage.py migrate maths 0004

# Restore code
git checkout main
```

### If something goes wrong AFTER data migrations (0006/0007):

Data migrations use `RunPython.noop` as reverse — they **cannot be auto-reversed**.

**Option A: Restore from backup (recommended)**
```bash
# Stop app
sudo systemctl stop gunicorn

# Restore database
mysql -u <user> -p <database_name> < backup_YYYYMMDD_HHMMSS.sql

# Restore code
git checkout main

# Start app
sudo systemctl start gunicorn
```

**Option B: Manual rollback (advanced)**
```sql
-- Reverse maths 0007: Drop the table_number column
ALTER TABLE maths_studentfinalanswer DROP COLUMN table_number;
DELETE FROM django_migrations WHERE app='maths' AND name='0007_add_table_number_to_studentfinalanswer';

-- Reverse maths 0006: Reset backfilled scores (DANGEROUS — only if you must)
-- This would zero out scores that were correctly backfilled.
-- Only use this if you're sure you want to lose the backfilled data.
-- UPDATE maths_studentfinalanswer SET score=0, total_questions=0 WHERE ...;
DELETE FROM django_migrations WHERE app='maths' AND name='0006_backfill_final_answer_scores';

-- Then reverse schema migrations normally
python manage.py migrate classroom 0032
python manage.py migrate maths 0004
```

---

## 6. Environment-Specific Notes

### TEST Environment
- Run `python manage.py migrate` freely — test data can be reset if needed
- Use this to validate the data migration timing on a realistic dataset
- Test all quiz types (topic, basic facts, times tables 1-12) end-to-end
- Verify the dashboard shows correct data after migration

### PRODUCTION Environment
- **Schedule a maintenance window** (5-15 minutes depending on data volume)
- **Always backup first** — the data migrations are not reversible
- Monitor the `maths 0006` migration output — it prints the count of backfilled rows
- Monitor the `maths 0007` migration output — it prints the count of backfilled table_number values
- If the data migration is slow (>1000 rows), consider running it in a tmux/screen session

### Local Dev (already done)
- Migration 0007 was applied with `--fake` + manual backfill (due to partial application)
- 136 times-table records were backfilled
- This is NOT needed on fresh environments — the migration runs cleanly

---

## 7. New Database Tables Created

| Table | App | Purpose |
|-------|-----|---------|
| `classroom_school` | classroom | School/institute entity |
| `classroom_department` | classroom | Department within a school |
| `classroom_departmentteacher` | classroom | Teacher ↔ Department join table |
| `classroom_schoolteacher` | classroom | Teacher ↔ School join table with role |
| `classroom_schoolstudent` | classroom | Student ↔ School join table |
| `classroom_classsession` | classroom | Individual class session (date/time) |
| `classroom_studentattendance` | classroom | Student attendance per session |
| `classroom_teacherattendance` | classroom | Teacher attendance per session |
| `classroom_progresscriteria` | classroom | Hierarchical progress tracking criteria |
| `classroom_progressrecord` | classroom | Per-student per-session progress records |
| `classroom_topiclevel` | classroom | Topic ↔ Level linking (if not inline M2M) |

## 8. Modified Database Columns

| Table | Column | Change |
|-------|--------|--------|
| `classroom_classroom` | `department_id` | New nullable FK to Department |
| `classroom_classroom` | `day`, `start_time`, `end_time`, `description` | New scheduling fields |
| `classroom_level` | `school_id` | New nullable FK to School |
| `classroom_classsession` | `created_by_id` | New nullable FK to User |
| `classroom_studentattendance` | `approved_at`, `approved_by_id`, `self_reported` | New approval workflow fields |
| `classroom_progresscriteria` | `parent_id` | New self-FK for hierarchy |
| `maths_question` | `school_id` | New nullable FK to School |
| `maths_studentfinalanswer` | `table_number` | New field for times-table number (1-12) |
