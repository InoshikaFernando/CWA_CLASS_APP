"""
Repair migration: add the grading-review columns to
``homework_homeworkstudentanswer`` on environments where they are missing.

Root cause: ``0006_create_missing_answer_tables`` recreates this table with
``CREATE TABLE IF NOT EXISTS`` using ONLY the base columns (text_answer,
is_correct, points_earned, the two legacy FKs, submission_id). On the legacy
prod DB the table already existed in that minimal shape, so the later
``AddField`` migrations (0008 / 0009 / 0012) that introduce the review fields
were faked rather than applied — leaving Django's migration state marking them
as applied while the columns never actually landed.

Symptom on prod:
  OperationalError: (1054, "Unknown column 'review_status' in 'field list'")
  at homework/views.py bulk_create() on every student homework submission.

This migration is idempotent: it inspects the live schema and only adds the
columns that are genuinely missing, using ``schema_editor.add_field`` so the
DDL (types, defaults, the graded_by FK to accounts_customuser) matches exactly
what the model expects. On healthy environments (test, fresh installs) every
column already exists, so it is a no-op.
"""

from django.db import migrations

# Model field names that 0008/0009/0012 were meant to add.
REVIEW_FIELDS = [
    'review_status',
    'ai_feedback',
    'ai_score_fraction',
    'teacher_feedback',
    'graded_by',
    'graded_at',
]


def _existing_columns(conn, table):
    with conn.cursor() as cur:
        if conn.vendor == 'sqlite':
            cur.execute(f'PRAGMA table_info("{table}")')
            return {row[1] for row in cur.fetchall()}
        cur.execute(
            """
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            [table],
        )
        return {row[0] for row in cur.fetchall()}


def add_missing_columns(apps, schema_editor):
    Model = apps.get_model('homework', 'HomeworkStudentAnswer')
    conn = schema_editor.connection
    existing = _existing_columns(conn, Model._meta.db_table)

    for field_name in REVIEW_FIELDS:
        field = Model._meta.get_field(field_name)
        if field.column not in existing:
            schema_editor.add_field(Model, field)


class Migration(migrations.Migration):

    # DDL must run outside a transaction: MySQL can't roll back DDL, so calling
    # schema_editor.add_field() inside the default atomic migration transaction
    # raises TransactionManagementError. The per-column existence check keeps
    # this safely re-runnable even without atomic wrapping.
    atomic = False

    dependencies = [
        ('homework', '0019_merge_20260614_1229'),
    ]

    operations = [
        migrations.RunPython(
            add_missing_columns,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
