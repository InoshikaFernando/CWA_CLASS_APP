"""
Add question_type to CodingExercise and create CodingAnswer model.

Both objects may already exist in MySQL (created on a prior branch or manually).
Every DB operation is guarded so the migration is safe to run in any state.
"""
import django.db.models.deletion
from django.db import migrations, models


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _column_exists(connection, table, column):
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "  AND TABLE_NAME  = %s AND COLUMN_NAME = %s",
                [table, column],
            )
            return cursor.fetchone()[0] > 0
        elif vendor == 'postgresql':
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                [table, column],
            )
            return cursor.fetchone()[0] > 0
        else:  # sqlite
            cursor.execute(f"PRAGMA table_info({table})")
            return any(row[1] == column for row in cursor.fetchall())


def _table_exists(connection, table):
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                [table],
            )
            return cursor.fetchone()[0] > 0
        elif vendor == 'postgresql':
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = %s",
                [table],
            )
            return cursor.fetchone()[0] > 0
        else:  # sqlite
            cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=%s",
                [table],
            )
            return cursor.fetchone()[0] > 0


# ---------------------------------------------------------------------------
# RunPython callables
# ---------------------------------------------------------------------------

def _apply(apps, schema_editor):
    conn = schema_editor.connection

    # 1. Add question_type column if missing
    if not _column_exists(conn, 'coding_codingexercise', 'question_type'):
        schema_editor.add_field(
            apps.get_model('coding', 'CodingExercise'),
            models.CharField(
                name='question_type',
                max_length=20,
                default='write_code',
            ),
        )

    # 2. Create coding_codinganswer table if missing
    if not _table_exists(conn, 'coding_codinganswer'):
        schema_editor.create_model(apps.get_model('coding', 'CodingAnswer'))


def _noop(apps, schema_editor):
    pass


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0012_add_exercise_uses_browser_sandbox'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # state_operations always run — keep Django's internal model state correct
            state_operations=[
                migrations.AddField(
                    model_name='codingexercise',
                    name='question_type',
                    field=models.CharField(
                        choices=[
                            ('write_code',      'Write Code'),
                            ('multiple_choice', 'Multiple Choice'),
                            ('true_false',      'True / False'),
                            ('short_answer',    'Short Answer'),
                            ('fill_blank',      'Fill in the Blank'),
                        ],
                        default='write_code',
                        max_length=20,
                        help_text=(
                            'write_code (default) keeps existing behaviour. '
                            'Other types allow use in BrainBuzz sessions.'
                        ),
                    ),
                ),
                migrations.CreateModel(
                    name='CodingAnswer',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('answer_text', models.CharField(max_length=500)),
                        ('is_correct', models.BooleanField(default=False)),
                        ('order', models.PositiveSmallIntegerField(default=0)),
                        ('exercise', models.ForeignKey(
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name='answers',
                            to='coding.codingexercise',
                        )),
                    ],
                    options={'ordering': ['exercise', 'order']},
                ),
            ],
            # database_operations guard each DDL statement individually
            database_operations=[
                migrations.RunPython(_apply, _noop),
            ],
        ),
    ]
