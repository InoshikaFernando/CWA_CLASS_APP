"""
Migration: re-run the legacy schema fixes that 0004 missed on PythonAnywhere.

Root cause of 0004 failure:
  MySQLdb on PythonAnywhere returns information_schema string columns as bytes
  (e.g. b'NO') rather than str ('NO').  The equality checks
    info[1] == 'NO'   and   info[2] is None
  both evaluated to False, so no ALTER TABLE was ever executed.

Fix:
  Drop the nullable/default condition checks entirely.  If the column exists,
  always run MODIFY COLUMN / ALTER COLUMN.  Running these on a column that
  already has the target state is a MySQL no-op and causes no harm.
"""

from django.db import migrations


def _column_exists_mysql(cursor, table, column):
    cursor.execute(
        "SELECT 1 FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "  AND TABLE_NAME = %s "
        "  AND COLUMN_NAME = %s",
        [table, column],
    )
    return cursor.fetchone() is not None


def _fix_homework_table(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor == 'sqlite':
        return  # fresh SQLite test DBs are built correctly from models

    with conn.cursor() as cur:
        # Make nullable — always run if column exists (idempotent)
        if _column_exists_mysql(cur, 'homework_homework', 'assigned_date'):
            cur.execute(
                "ALTER TABLE homework_homework "
                "MODIFY COLUMN assigned_date datetime(6) NULL DEFAULT NULL"
            )

        if _column_exists_mysql(cur, 'homework_homework', 'is_active'):
            cur.execute(
                "ALTER TABLE homework_homework "
                "MODIFY COLUMN is_active tinyint(1) NOT NULL DEFAULT 1"
            )

        if _column_exists_mysql(cur, 'homework_homework', 'status'):
            cur.execute(
                "ALTER TABLE homework_homework "
                "MODIFY COLUMN status varchar(20) NOT NULL DEFAULT 'published'"
            )

        if _column_exists_mysql(cur, 'homework_homework', 'max_attempts'):
            cur.execute(
                "ALTER TABLE homework_homework "
                "MODIFY COLUMN max_attempts int unsigned NULL DEFAULT NULL"
            )


def _fix_submission_table(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor == 'sqlite':
        return

    with conn.cursor() as cur:
        if _column_exists_mysql(cur, 'homework_homeworksubmission', 'is_late'):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN is_late tinyint(1) NOT NULL DEFAULT 0"
            )

        if _column_exists_mysql(cur, 'homework_homeworksubmission', 'content'):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN content longtext NULL"
            )

        if _column_exists_mysql(cur, 'homework_homeworksubmission', 'feedback'):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN feedback longtext NULL"
            )

        if _column_exists_mysql(cur, 'homework_homeworksubmission', 'is_graded'):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN is_graded tinyint(1) NOT NULL DEFAULT 0"
            )

        if _column_exists_mysql(cur, 'homework_homeworksubmission', 'is_published'):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN is_published tinyint(1) NOT NULL DEFAULT 0"
            )

        if _column_exists_mysql(
            cur, 'homework_homeworksubmission', 'is_auto_completed'
        ):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN is_auto_completed tinyint(1) NOT NULL DEFAULT 0"
            )

        if _column_exists_mysql(
            cur, 'homework_homeworksubmission', 'quiz_session_id'
        ):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "MODIFY COLUMN quiz_session_id varchar(100) NOT NULL DEFAULT ''"
            )

        # Add missing columns if absent (these are safe to run on any DB)
        if not _column_exists_mysql(
            cur, 'homework_homeworksubmission', 'total_questions'
        ):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "ADD COLUMN total_questions smallint unsigned NOT NULL DEFAULT 0"
            )

        if not _column_exists_mysql(cur, 'homework_homeworksubmission', 'points'):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "ADD COLUMN points double NOT NULL DEFAULT 0"
            )

        if not _column_exists_mysql(
            cur, 'homework_homeworksubmission', 'time_taken_seconds'
        ):
            cur.execute(
                "ALTER TABLE homework_homeworksubmission "
                "ADD COLUMN time_taken_seconds int unsigned NOT NULL DEFAULT 0"
            )


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0004_fix_legacy_schema'),
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
