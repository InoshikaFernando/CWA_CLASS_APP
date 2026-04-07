"""
Migration: ensure homework_homework.description column exists.

Root cause (CPP-137 / Avinesh's second comment):
  IntegrityError (1364, "Field 'description' doesn't have a default value")
  at POST /homework/class/32/create/.

  The deployed DB has a description column that is NOT NULL with no default
  (created from an older version of 0001_initial).  Our current model had no
  description field, so Django never sent a value → MySQL strict mode rejected
  the INSERT.

Fix:
  - description is added to the Homework model with blank=True, default=''.
    Django will now include description='' in every INSERT, satisfying the
    NOT NULL constraint without needing a DB-level default.
  - This migration ensures the column exists on every deployment:
      A) Column absent (new MySQL or SQLite)    → ADD COLUMN … NULL
      B) Column exists already (Avinesh's DB)  → no-op (Django sends value)
  - SeparateDatabaseAndState updates Django's migration state; all physical
    DDL is handled by the RunPython step so we never hit MySQL 5.7's
    restriction that TEXT columns cannot have a default value.
"""

from django.db import migrations, models


def _ensure_description_column(apps, schema_editor):
    connection = schema_editor.connection

    if connection.vendor == 'sqlite':
        # Use PRAGMA to check column presence on SQLite (test / local dev).
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(homework_homework)")
            columns = [row[1] for row in cursor.fetchall()]
        if 'description' not in columns:
            with connection.cursor() as cursor:
                # SQLite allows adding a nullable column to an existing table.
                cursor.execute(
                    "ALTER TABLE homework_homework "
                    "ADD COLUMN description TEXT NULL"
                )
        return

    # MySQL / MariaDB ─────────────────────────────────────────────────────────
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "  AND TABLE_NAME = 'homework_homework' "
            "  AND COLUMN_NAME = 'description'"
        )
        column_exists = cursor.fetchone() is not None

    if not column_exists:
        # Add as nullable — avoids MySQL 5.7 "TEXT can't have a default"
        # restriction and is safe when existing rows already exist.
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE homework_homework "
                "ADD COLUMN description LONGTEXT NULL"
            )
    # If column already exists (Avinesh's case): Django now sends description=''
    # on every INSERT (model default=''), so the NOT NULL constraint is satisfied
    # without any column modification.


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0002_add_created_by_nullable'),
    ]

    operations = [
        # Step 1 — ensure the physical column exists on every deployment.
        migrations.RunPython(
            _ensure_description_column,
            reverse_code=migrations.RunPython.noop,
        ),
        # Step 2 — update Django's migration state only; all DB DDL was
        # handled above so we use empty database_operations here.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='homework',
                    name='description',
                    field=models.TextField(blank=True, default=''),
                ),
            ],
            database_operations=[],
        ),
    ]
