"""
Migration 0007: re-apply all legacy schema fixes from 0004.

0004 was faked on the restored production DB (and some dev environments),
so the ALTER TABLE statements never executed.  All operations here are
idempotent — they check current state before acting — so running them
again on a DB where 0004 DID apply is harmless.

Fixes applied (same as 0004, now guaranteed to run):

  homework_homework
  -----------------
  assigned_date    → NULL DEFAULT NULL
  is_active        → DEFAULT 1
  status           → DEFAULT 'published'
  max_attempts     → NULL DEFAULT NULL

  homework_homeworksubmission
  ---------------------------
  is_late          → DEFAULT 0
  content          → NULL  (LONGTEXT cannot have a DEFAULT)
  feedback         → NULL
  is_graded        → DEFAULT 0
  is_published     → DEFAULT 0
  is_auto_completed→ DEFAULT 0
  quiz_session_id  → DEFAULT ''
  total_questions  → ADD COLUMN if missing, DEFAULT 0
  points           → ADD COLUMN if missing, DEFAULT 0
  time_taken_seconds → ADD COLUMN if missing, DEFAULT 0
"""

from django.db import migrations


# ── helpers ───────────────────────────────────────────────────────────────────

def _col(cursor, table, column, vendor):
    """Return information_schema row for column, or None if absent."""
    if vendor == 'sqlite':
        cursor.execute(f"PRAGMA table_info({table})")
        for row in cursor.fetchall():
            if row[1] == column:
                return row
        return None
    cursor.execute(
        "SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        [table, column],
    )
    return cursor.fetchone()


def _exists(cursor, table, column, vendor):
    return _col(cursor, table, column, vendor) is not None


# ── homework_homework ─────────────────────────────────────────────────────────

def _fix_homework(apps, schema_editor):
    conn = schema_editor.connection
    v = conn.vendor

    with conn.cursor() as c:
        if v == 'sqlite':
            return  # fresh SQLite DB has correct schema from model definitions

        info = _col(c, 'homework_homework', 'assigned_date', v)
        if info and info[1] == 'NO':
            c.execute("ALTER TABLE homework_homework "
                      "MODIFY COLUMN assigned_date datetime(6) NULL DEFAULT NULL")

        info = _col(c, 'homework_homework', 'is_active', v)
        if info and info[2] is None:
            c.execute("ALTER TABLE homework_homework "
                      "MODIFY COLUMN is_active tinyint(1) NOT NULL DEFAULT 1")

        info = _col(c, 'homework_homework', 'status', v)
        if info and info[2] is None:
            c.execute("ALTER TABLE homework_homework "
                      "MODIFY COLUMN status varchar(20) NOT NULL DEFAULT 'published'")

        info = _col(c, 'homework_homework', 'max_attempts', v)
        if info and info[1] == 'NO':
            c.execute("ALTER TABLE homework_homework "
                      "MODIFY COLUMN max_attempts int unsigned NULL DEFAULT NULL")


# ── homework_homeworksubmission ───────────────────────────────────────────────

def _fix_submission(apps, schema_editor):
    conn = schema_editor.connection
    v = conn.vendor

    with conn.cursor() as c:
        if v != 'sqlite':
            # Legacy NOT NULL columns → add safe defaults
            mods = [
                ('is_late',           "MODIFY COLUMN is_late tinyint(1) NOT NULL DEFAULT 0",          'default'),
                ('content',           "MODIFY COLUMN content longtext NULL",                           'nullable'),
                ('feedback',          "MODIFY COLUMN feedback longtext NULL",                          'nullable'),
                ('is_graded',         "MODIFY COLUMN is_graded tinyint(1) NOT NULL DEFAULT 0",         'default'),
                ('is_published',      "MODIFY COLUMN is_published tinyint(1) NOT NULL DEFAULT 0",      'default'),
                ('is_auto_completed', "MODIFY COLUMN is_auto_completed tinyint(1) NOT NULL DEFAULT 0", 'default'),
                ('quiz_session_id',   "MODIFY COLUMN quiz_session_id varchar(100) NOT NULL DEFAULT ''", 'default'),
            ]
            for col, sql, check in mods:
                info = _col(c, 'homework_homeworksubmission', col, v)
                if info is None:
                    continue
                if check == 'default' and info[2] is None:
                    c.execute(f"ALTER TABLE homework_homeworksubmission {sql}")
                elif check == 'nullable' and info[1] == 'NO':
                    c.execute(f"ALTER TABLE homework_homeworksubmission {sql}")

        # ADD missing model columns (same SQL for both vendors)
        adds = [
            ('total_questions',    "ADD COLUMN total_questions smallint unsigned NOT NULL DEFAULT 0"),
            ('points',             "ADD COLUMN points double NOT NULL DEFAULT 0"),
            ('time_taken_seconds', "ADD COLUMN time_taken_seconds int unsigned NOT NULL DEFAULT 0"),
        ]
        for col, sql in adds:
            if not _exists(c, 'homework_homeworksubmission', col, v):
                c.execute(f"ALTER TABLE homework_homeworksubmission {sql}")


# ── migration ─────────────────────────────────────────────────────────────────

class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0006_create_missing_answer_tables'),
    ]

    operations = [
        migrations.RunPython(_fix_homework,    reverse_code=migrations.RunPython.noop),
        migrations.RunPython(_fix_submission,  reverse_code=migrations.RunPython.noop),
    ]
