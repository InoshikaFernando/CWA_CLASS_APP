"""
Reconcile Django model state with the MySQL schema produced by a prior branch,
and ensure the schema is created correctly on fresh test databases.

What the DB already has (verified against prod-shaped MySQL):
  coding_codingexercise  — correct_short_answer  LONGTEXT NULL
  coding_codinganswer    — answer_text            LONGTEXT  (was VARCHAR 500)
  coding_codinganswer    — created_at / updated_at  datetime(6)
  coding_codinganswer    — FK column name is "coding_exercise_id" (not "exercise_id")

Strategy: SeparateDatabaseAndState
  state_operations  — bring Django's internal model state up to date.
  database_operations — RunPython with per-column guards:
    * On prod MySQL: all columns already exist → every guard skips → noop.
    * On fresh test DB: columns were not created by 0013 → guards add them.
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


# ---------------------------------------------------------------------------
# Helpers (duplicated from 0013 — migrations must not import each other)
# ---------------------------------------------------------------------------

def _column_exists(connection, table, column):
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "  AND TABLE_NAME = %s AND COLUMN_NAME = %s",
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


def _add_datetime_col(conn, table, column):
    """Add a NOT NULL datetime column with a static default (vendor-aware)."""
    vendor = conn.vendor
    with conn.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(
                f"ALTER TABLE `{table}` "
                f"ADD COLUMN `{column}` datetime(6) NOT NULL "
                f"DEFAULT '2000-01-01 00:00:00.000000'"
            )
        elif vendor == 'postgresql':
            cursor.execute(
                f'ALTER TABLE "{table}" '
                f'ADD COLUMN "{column}" timestamp with time zone NOT NULL '
                f"DEFAULT '2000-01-01 00:00:00+00'"
            )
        else:  # sqlite
            cursor.execute(
                f'ALTER TABLE "{table}" '
                f'ADD COLUMN "{column}" datetime NOT NULL '
                f"DEFAULT '2000-01-01 00:00:00'"
            )


# ---------------------------------------------------------------------------
# RunPython callables
# ---------------------------------------------------------------------------

def _apply(apps, schema_editor):
    conn = schema_editor.connection

    # 1. correct_short_answer on coding_codingexercise
    if not _column_exists(conn, 'coding_codingexercise', 'correct_short_answer'):
        Exercise = apps.get_model('coding', 'CodingExercise')
        field = models.TextField(null=True, blank=True)
        field.set_attributes_from_name('correct_short_answer')
        schema_editor.add_field(Exercise, field)

    # 2. created_at on coding_codinganswer
    if not _column_exists(conn, 'coding_codinganswer', 'created_at'):
        _add_datetime_col(conn, 'coding_codinganswer', 'created_at')

    # 3. updated_at on coding_codinganswer
    if not _column_exists(conn, 'coding_codinganswer', 'updated_at'):
        _add_datetime_col(conn, 'coding_codinganswer', 'updated_at')

    # Note: answer_text varchar→text and the FK column rename (exercise_id →
    # coding_exercise_id) are state-only reconciliations:
    #   • On prod MySQL: those changes were applied by a prior branch.
    #   • On a fresh test DB: migration 0013 created coding_codinganswer with
    #     coding_exercise_id already, so no rename is needed; varchar(500) is
    #     compatible with TextField for our test data (<500 chars).


def _noop(apps, schema_editor):
    pass


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0013_add_question_type_coding_answer'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # ── State only: align Django's understanding of the schema ──────
            state_operations=[

                # 1. CodingExercise — add correct_short_answer
                migrations.AddField(
                    model_name='codingexercise',
                    name='correct_short_answer',
                    field=models.TextField(
                        blank=True,
                        null=True,
                        help_text=(
                            'Required for short_answer and fill_blank question types. '
                            'Unused for other types.'
                        ),
                    ),
                ),

                # 2. CodingAnswer — FK db_column matches actual MySQL column name
                migrations.AlterField(
                    model_name='codinganswer',
                    name='exercise',
                    field=models.ForeignKey(
                        db_column='coding_exercise_id',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='answers',
                        to='coding.codingexercise',
                    ),
                ),

                # 3. CodingAnswer — widen answer_text to TextField
                migrations.AlterField(
                    model_name='codinganswer',
                    name='answer_text',
                    field=models.TextField(),
                ),

                # 4. CodingAnswer — timestamps
                migrations.AddField(
                    model_name='codinganswer',
                    name='created_at',
                    field=models.DateTimeField(
                        auto_now_add=True,
                        default=django.utils.timezone.now,
                    ),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name='codinganswer',
                    name='updated_at',
                    field=models.DateTimeField(
                        auto_now=True,
                        default=django.utils.timezone.now,
                    ),
                    preserve_default=False,
                ),
            ],

            # ── DB: guarded per-column to handle both prod and fresh DBs ────
            database_operations=[
                migrations.RunPython(_apply, _noop),
            ],
        ),
    ]
