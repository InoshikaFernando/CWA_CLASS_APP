"""
Migration: ensure homework_homework.created_by_id column exists and is nullable.

Root cause (CPP-137 / Avinesh's comment):
  On some deployed environments the homework table was created from an older
  version of 0001_initial that did NOT include created_by.  When the field was
  later added to the model the migration file was edited in-place rather than
  creating a new migration, so `manage.py migrate` considered 0001_initial
  already applied and skipped it — leaving the column absent.

This migration:
  1. (RunPython) Adds created_by_id as a bare nullable INT column when it is
     missing.  Uses information_schema so it works on MySQL 5.7 and 8.0.
     No-op on SQLite (tests always use a fresh schema).
  2. (AlterField) Formally registers the ForeignKey relationship / index in
     Django's migration state, and ensures the column is nullable so that
     rows created before the field was introduced are not rejected.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _add_column_if_missing(apps, schema_editor):
    """Add created_by_id to homework_homework only if the column is absent."""
    if schema_editor.connection.vendor == 'sqlite':
        # SQLite test databases are always created from scratch — the column
        # already exists from 0001_initial, nothing to do.
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "  AND TABLE_NAME = 'homework_homework' "
            "  AND COLUMN_NAME = 'created_by_id'"
        )
        column_exists = cursor.fetchone()[0] > 0

    if not column_exists:
        with schema_editor.connection.cursor() as cursor:
            # Add as a plain nullable INT so existing rows are valid.
            # The AlterField operation below will register the FK constraint.
            cursor.execute(
                "ALTER TABLE homework_homework "
                "ADD COLUMN created_by_id INT(11) NULL"
            )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('homework', '0001_initial'),
    ]

    operations = [
        # Step 1 — ensure the physical column exists on every deployment.
        migrations.RunPython(
            _add_column_if_missing,
            reverse_code=migrations.RunPython.noop,
        ),
        # Step 2 — make the field nullable in Django's state and add the FK
        # index/constraint (safe even when the column already exists).
        migrations.AlterField(
            model_name='homework',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_homework',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
