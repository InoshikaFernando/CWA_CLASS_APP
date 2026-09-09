"""Migration 0028: reconcile ``HomeworkSubmission.score`` with its model (CPP-408).

Production holds this column as ``decimal(6,2)`` while the model has always
declared ``PositiveSmallIntegerField``. Nothing in ``homework/migrations/``
ever altered it — ``0001_initial`` created it as a small integer and no
``AlterField`` follows — so the widening was done straight against the
database, presumably to hold partial-credit scores, and never written down.

Why no existing check caught it
-------------------------------
``makemigrations --check`` compares models to migration STATE, never to the
live database. ``migrate`` will not fix it. ``check --deploy`` does not look.
The drift is invisible to every guard in CI, which is how it survived.

Why it is worth fixing even though nothing is broken
----------------------------------------------------
No row uses the extra precision, so no mark is wrong today. But reads come
back as ``Decimal`` rather than ``int``, and ``json.dumps`` refuses a Decimal —
so any path that re-reads a submission and serialises its score into a
``JsonResponse`` or an audit ``detail`` blob would 500. And if anyone ever
generates the "obvious" migration to correct this column, Django would round
every fractional score without a word, because from its point of view the
column was always meant to be an integer.

Why not a plain AlterField
--------------------------
Migration state already SAYS ``PositiveSmallIntegerField``, so Django compares
old field to new field, sees no difference, and emits no SQL at all. The ALTER
has to be issued explicitly. Same reason ``maths/0012`` reaches for RunSQL.

Safety
------
* MySQL only — SQLite (the test suites) is left alone, so this is a no-op there.
* Idempotent — reads ``information_schema`` first and skips when the column is
  already right, so a re-run costs nothing and a half-applied deploy resumes.
* **Refuses rather than rounds.** The count of fractional scores was 0 when
  this was written, but rows can appear between then and the deploy, so it is
  checked at migrate time. A row that would lose data stops the migration with
  a message naming the rows, instead of silently truncating a child's mark.
* Reversible — the reverse restores ``decimal(6,2)``, which is what production
  holds today.
* **Non-atomic**, like ``0020``. MySQL cannot roll DDL back, and Django refuses
  to issue DDL from ``RunPython`` inside a transaction on such a database
  ("Executing DDL statements while in a transaction on databases that can't
  perform a rollback is prohibited") — which is exactly how the first deploy
  of this migration failed on the test site. The SQLite suites never hit it,
  because SQLite's DDL is transactional. Nothing here needs the transaction:
  the checks before the ALTER only read, and the ALTER is a single statement.

The target type is DERIVED from the model field rather than hard-coded, so it
cannot drift from what Django would create for a fresh install.
"""
from django.db import migrations

TABLE = 'homework_homeworksubmission'
COLUMN = 'score'

# What production holds now, restored by the reverse.
LEGACY_TYPE = 'decimal(6,2)'


def _column_data_type(connection):
    """The live column's ``DATA_TYPE``, or None when it cannot be read."""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT DATA_TYPE FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s '
            'AND COLUMN_NAME = %s',
            [TABLE, COLUMN],
        )
        row = cursor.fetchone()
    return row[0].lower() if row else None


def _target_definition(apps, connection):
    """``<db type> <NULL|NOT NULL>`` for the model's own field.

    Derived from the field so it matches what Django would create, rather than
    a hard-coded string that can drift from the model it is meant to track.
    """
    field = apps.get_model('homework', 'HomeworkSubmission')._meta.get_field(COLUMN)
    return f'{field.db_type(connection)} {"NULL" if field.null else "NOT NULL"}'


def _refuse_if_data_would_be_lost(connection):
    """Stop the migration if any row holds a score the target type cannot keep.

    No silent failure: a fractional score is somebody's mark, and rounding it
    away during a deploy would be both invisible and unrecoverable.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT id, {COLUMN} FROM {TABLE} '
            f'WHERE {COLUMN} <> ROUND({COLUMN}) LIMIT 10'
        )
        rows = cursor.fetchall()
    if rows:
        listed = ', '.join(f'#{pk} = {value}' for pk, value in rows)
        raise RuntimeError(
            f'{TABLE}.{COLUMN} holds fractional values, which a small integer '
            f'cannot keep: {listed}. Refusing to round somebody\'s mark away '
            f'in a deploy. Decide what those scores should be — and whether '
            f'the MODEL is the thing that is wrong — before running this.'
        )


def align_to_model(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return                                  # SQLite test databases are fine
    if _column_data_type(connection) == 'smallint':
        return                                  # already reconciled
    _refuse_if_data_would_be_lost(connection)
    schema_editor.execute(
        f'ALTER TABLE {TABLE} MODIFY {COLUMN} '
        f'{_target_definition(apps, connection)}'
    )


def restore_legacy_column(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return
    if _column_data_type(connection) == 'decimal':
        return
    schema_editor.execute(
        f'ALTER TABLE {TABLE} MODIFY {COLUMN} {LEGACY_TYPE} NOT NULL'
    )


class Migration(migrations.Migration):

    # DDL from RunPython on MySQL must run outside a transaction (see Safety).
    atomic = False

    dependencies = [
        ('homework', '0027_questionschedule_scheduleweek_and_more'),
    ]

    operations = [
        # No state change: the state already declares the field correctly.
        # This migration exists only to make the DATABASE agree with it.
        migrations.RunPython(align_to_model, restore_legacy_column),
    ]
