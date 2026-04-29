"""
Add question_type to CodingExercise and create CodingAnswer model.

Both objects may already exist in MySQL (created on a prior branch or manually).
Every DB operation is guarded so the migration is safe to run in any state.

CodingAnswer is created via raw DDL instead of schema_editor.create_model() because
models defined in the *same* migration's state_operations are not reliably accessible
via apps.get_model() inside a SeparateDatabaseAndState RunPython callable.
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


def _create_codinganswer_table_ddl(conn):
    """Create coding_codinganswer using raw DDL (vendor-aware).

    Uses coding_exercise_id as the FK column name to match the column name
    already present on the production MySQL instance from a prior branch.
    """
    vendor = conn.vendor
    with conn.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(
                "CREATE TABLE `coding_codinganswer` ("
                " `id` bigint NOT NULL AUTO_INCREMENT,"
                " `answer_text` varchar(500) NOT NULL,"
                " `is_correct` tinyint(1) NOT NULL DEFAULT 0,"
                " `order` smallint UNSIGNED NOT NULL DEFAULT 0,"
                " `coding_exercise_id` bigint NOT NULL,"
                " PRIMARY KEY (`id`),"
                " CONSTRAINT `coding_codinganswer_exercise_id_fk`"
                "  FOREIGN KEY (`coding_exercise_id`)"
                "  REFERENCES `coding_codingexercise` (`id`) ON DELETE CASCADE"
                ") DEFAULT CHARSET=utf8mb4"
            )
        elif vendor == 'postgresql':
            cursor.execute(
                'CREATE TABLE "coding_codinganswer" ('
                ' "id" bigserial NOT NULL PRIMARY KEY,'
                ' "answer_text" varchar(500) NOT NULL,'
                ' "is_correct" boolean NOT NULL DEFAULT FALSE,'
                ' "order" smallint NOT NULL DEFAULT 0,'
                ' "coding_exercise_id" bigint NOT NULL,'
                ' CONSTRAINT "coding_codinganswer_exercise_id_fk"'
                '  FOREIGN KEY ("coding_exercise_id")'
                '  REFERENCES "coding_codingexercise" ("id") ON DELETE CASCADE'
                ")"
            )
        else:  # sqlite
            cursor.execute(
                'CREATE TABLE "coding_codinganswer" ('
                ' "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,'
                ' "answer_text" varchar(500) NOT NULL,'
                ' "is_correct" bool NOT NULL DEFAULT 0,'
                ' "order" smallint NOT NULL DEFAULT 0,'
                ' "coding_exercise_id" integer NOT NULL,'
                ' FOREIGN KEY ("coding_exercise_id")'
                '  REFERENCES "coding_codingexercise" ("id") ON DELETE CASCADE'
                ")"
            )


# ---------------------------------------------------------------------------
# RunPython callables
# ---------------------------------------------------------------------------

def _apply(apps, schema_editor):
    conn = schema_editor.connection

    # 1. Add question_type column if missing.
    # set_attributes_from_name() sets .name / .attname / .column on the field
    # object so schema_editor can derive the DDL.
    if not _column_exists(conn, 'coding_codingexercise', 'question_type'):
        Exercise = apps.get_model('coding', 'CodingExercise')
        field = models.CharField(max_length=20, default='write_code')
        field.set_attributes_from_name('question_type')
        schema_editor.add_field(Exercise, field)

    # 2. Create coding_codinganswer table if missing.
    # Raw DDL is used here because apps.get_model('coding', 'CodingAnswer')
    # is unreliable when CodingAnswer is defined in the *same* migration's
    # state_operations — the model may not yet exist in the historical state
    # exposed to database_operations RunPython callables.
    if not _table_exists(conn, 'coding_codinganswer'):
        _create_codinganswer_table_ddl(conn)


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
