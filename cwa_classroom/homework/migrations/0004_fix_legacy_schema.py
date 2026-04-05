"""
Migration: reconcile legacy DB schema with the current Homework app models.

Root cause (CPP-137 — identified from cwa_backup_20260405_172148.sql):
  Avinesh's test environment was built from an older version of the codebase
  that had a significantly different `homework_homework` and
  `homework_homeworksubmission` schema.  Several columns are NOT NULL with no
  DB-level default; because our Django models don't include those legacy fields,
  MySQL strict mode raises IntegrityError on every INSERT.

  Additionally, our model has three columns (`total_questions`, `points`,
  `time_taken_seconds`) that are absent from the legacy submission table —
  causing OperationalError ("Unknown column …") on any query.

Fix strategy
────────────
  homework_homework — legacy NOT NULL columns we never send:
    • assigned_date    → make nullable
    • is_active        → add DEFAULT 1  (tinyint, MySQL allows this)
    • status           → add DEFAULT 'published'
    • max_attempts     → make nullable (model already marks it null=True)

  homework_homeworksubmission — legacy NOT NULL columns we never send:
    • is_late          → add DEFAULT 0
    • content          → make nullable  (LONGTEXT — cannot have a DEFAULT)
    • feedback         → make nullable
    • is_graded        → add DEFAULT 0
    • is_published     → add DEFAULT 0
    • is_auto_completed→ add DEFAULT 0
    • quiz_session_id  → add DEFAULT ''

  homework_homeworksubmission — our model columns absent from legacy table:
    • total_questions  → ADD COLUMN … NOT NULL DEFAULT 0
    • points           → ADD COLUMN … NOT NULL DEFAULT 0
    • time_taken_seconds → ADD COLUMN … NOT NULL DEFAULT 0

Each ALTER is wrapped in an existence/nullability check so the migration is
idempotent and safe on both fresh installs and Avinesh's legacy environment.
SQLite (CI / local dev) skips the MySQL-only ALTER TABLE statements but still
adds missing columns.
"""

from django.db import migrations


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _column_info(cursor, table, column, vendor):
    """Return the information_schema row for *column* in *table*, or None."""
    if vendor == 'sqlite':
        cursor.execute(f"PRAGMA table_info({table})")
        for row in cursor.fetchall():
            # row = (cid, name, type, notnull, dflt_value, pk)
            if row[1] == column:
                return row
        return None
    else:
        cursor.execute(
            "SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "  AND TABLE_NAME = %s "
            "  AND COLUMN_NAME = %s",
            [table, column],
        )
        return cursor.fetchone()


def _column_exists(cursor, table, column, vendor):
    return _column_info(cursor, table, column, vendor) is not None


# ─────────────────────────────────────────────────────────────────────────────
# homework_homework fixes
# ─────────────────────────────────────────────────────────────────────────────

def _fix_homework_table(apps, schema_editor):
    conn = schema_editor.connection
    vendor = conn.vendor

    with conn.cursor() as cur:
        # ── assigned_date: make nullable if column exists and is NOT NULL ──
        info = _column_info(cur, 'homework_homework', 'assigned_date', vendor)
        if info is not None:
            if vendor == 'sqlite':
                pass  # SQLite cannot ALTER column constraints; fresh DB = no issue
            else:
                # IS_NULLABLE = 'NO' means NOT NULL
                if info[1] == 'NO':
                    cur.execute(
                        "ALTER TABLE homework_homework "
                        "MODIFY COLUMN assigned_date datetime(6) NULL DEFAULT NULL"
                    )

        # ── is_active: add DEFAULT 1 if column exists and has no default ──
        info = _column_info(cur, 'homework_homework', 'is_active', vendor)
        if info is not None:
            if vendor == 'sqlite':
                pass  # pragma: no cover
            else:
                if info[2] is None:  # COLUMN_DEFAULT is NULL → no default set
                    cur.execute(
                        "ALTER TABLE homework_homework "
                        "MODIFY COLUMN is_active tinyint(1) NOT NULL DEFAULT 1"
                    )

        # ── status: add DEFAULT 'published' if column exists and has no default ──
        info = _column_info(cur, 'homework_homework', 'status', vendor)
        if info is not None:
            if vendor == 'sqlite':
                pass  # pragma: no cover
            else:
                if info[2] is None:
                    cur.execute(
                        "ALTER TABLE homework_homework "
                        "MODIFY COLUMN status varchar(20) NOT NULL DEFAULT 'published'"
                    )

        # ── max_attempts: make nullable if column exists and is NOT NULL ──
        info = _column_info(cur, 'homework_homework', 'max_attempts', vendor)
        if info is not None:
            if vendor == 'sqlite':
                pass  # pragma: no cover
            else:
                if info[1] == 'NO':
                    cur.execute(
                        "ALTER TABLE homework_homework "
                        "MODIFY COLUMN max_attempts int unsigned NULL DEFAULT NULL"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# homework_homeworksubmission fixes
# ─────────────────────────────────────────────────────────────────────────────

def _fix_submission_table(apps, schema_editor):
    conn = schema_editor.connection
    vendor = conn.vendor

    with conn.cursor() as cur:

        # ── Legacy NOT NULL columns — add safe defaults so our INSERTs succeed ──

        if vendor != 'sqlite':
            # is_late tinyint
            info = _column_info(cur, 'homework_homeworksubmission', 'is_late', vendor)
            if info is not None and info[2] is None:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN is_late tinyint(1) NOT NULL DEFAULT 0"
                )

            # content longtext — cannot have DEFAULT; make nullable
            info = _column_info(cur, 'homework_homeworksubmission', 'content', vendor)
            if info is not None and info[1] == 'NO':
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN content longtext NULL"
                )

            # feedback longtext — cannot have DEFAULT; make nullable
            info = _column_info(cur, 'homework_homeworksubmission', 'feedback', vendor)
            if info is not None and info[1] == 'NO':
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN feedback longtext NULL"
                )

            # is_graded tinyint
            info = _column_info(cur, 'homework_homeworksubmission', 'is_graded', vendor)
            if info is not None and info[2] is None:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN is_graded tinyint(1) NOT NULL DEFAULT 0"
                )

            # is_published tinyint
            info = _column_info(cur, 'homework_homeworksubmission', 'is_published', vendor)
            if info is not None and info[2] is None:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN is_published tinyint(1) NOT NULL DEFAULT 0"
                )

            # is_auto_completed tinyint
            info = _column_info(
                cur, 'homework_homeworksubmission', 'is_auto_completed', vendor
            )
            if info is not None and info[2] is None:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN is_auto_completed tinyint(1) NOT NULL DEFAULT 0"
                )

            # quiz_session_id varchar
            info = _column_info(
                cur, 'homework_homeworksubmission', 'quiz_session_id', vendor
            )
            if info is not None and info[2] is None:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "MODIFY COLUMN quiz_session_id varchar(100) NOT NULL DEFAULT ''"
                )

        # ── Our model columns absent from the legacy table — ADD if missing ──

        # total_questions  smallint unsigned
        if not _column_exists(cur, 'homework_homeworksubmission', 'total_questions', vendor):
            if vendor == 'sqlite':
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "ADD COLUMN total_questions smallint unsigned NOT NULL DEFAULT 0"
                )
            else:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "ADD COLUMN total_questions smallint unsigned NOT NULL DEFAULT 0"
                )

        # points  double precision
        if not _column_exists(cur, 'homework_homeworksubmission', 'points', vendor):
            if vendor == 'sqlite':
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "ADD COLUMN points double NOT NULL DEFAULT 0"
                )
            else:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "ADD COLUMN points double NOT NULL DEFAULT 0"
                )

        # time_taken_seconds  int unsigned
        if not _column_exists(
            cur, 'homework_homeworksubmission', 'time_taken_seconds', vendor
        ):
            if vendor == 'sqlite':
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "ADD COLUMN time_taken_seconds int unsigned NOT NULL DEFAULT 0"
                )
            else:
                cur.execute(
                    "ALTER TABLE homework_homeworksubmission "
                    "ADD COLUMN time_taken_seconds int unsigned NOT NULL DEFAULT 0"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────────────────────────────────────

class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0003_add_description_with_default'),
    ]

    operations = [
        migrations.RunPython(
            _fix_homework_table,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            _fix_submission_table,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
