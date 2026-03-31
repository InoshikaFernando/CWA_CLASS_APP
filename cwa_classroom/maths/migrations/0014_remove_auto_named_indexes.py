"""
Migration 0014: DB-only cleanup — drop legacy auto-named indexes if present.

Background
----------
Migration 0001 placed three auto-named indexes into the DB and the migration
state:

  maths_stude_student_ad30a8_idx  — StudentFinalAnswer (student, topic, level)
  maths_stude_student_2e8b01_idx  — StudentFinalAnswer (student, topic, level, attempt_number)
  maths_topic_level_i_267d9e_idx  — TopicLevelStatistics (level, topic)

Migration 0010 removed the old maths.topic / maths.level FK columns via
RemoveField state operations.  Django automatically removes any Meta.indexes
that reference dropped fields from the migration state at that point — so all
three auto-named index entries were already cleaned from the state inside 0010.
Migration 0010 step 6 then restored correct explicitly-named indexes (and
migration 0013 shortened the SFA ones further).

Result: after migrations 0001–0013 the migration state already matches
models.py perfectly — no state-side changes are needed here.

DB side only
------------
On databases that already ran 0010 the three columns were dropped, and MySQL
cascades column removal to associated indexes, so this RunPython is a no-op.
On any edge-case DB where the indexes survived, the guarded DROP INDEX removes
them safely (checks information_schema first).
"""
from django.db import migrations


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _drop_auto_indexes_if_exist(apps, schema_editor):
    """
    Drop the three auto-named indexes from the DB if they still exist.
    No-op when they are absent (idempotent).
    """
    if schema_editor.connection.vendor != 'mysql':
        return
    db_name = schema_editor.connection.settings_dict['NAME']
    targets = [
        ('maths_studentfinalanswer',   'maths_stude_student_ad30a8_idx'),
        ('maths_studentfinalanswer',   'maths_stude_student_2e8b01_idx'),
        ('maths_topiclevelstatistics', 'maths_topic_level_i_267d9e_idx'),
    ]
    with schema_editor.connection.cursor() as cursor:
        for table_name, index_name in targets:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = %s "
                "  AND table_name   = %s "
                "  AND index_name   = %s",
                [db_name, table_name, index_name],
            )
            if cursor.fetchone()[0] == 0:
                continue  # Already gone — skip
            cursor.execute(
                f"ALTER TABLE `{table_name}` DROP INDEX `{index_name}`"
            )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ("maths", "0013_shorten_sfa_index_names"),
    ]

    operations = [
        # DB-only: drop any surviving auto-named indexes.
        # No state operations — the state was already corrected by migration
        # 0010's RemoveField cascade (auto-removes indexes on dropped fields).
        migrations.RunPython(
            _drop_auto_indexes_if_exist,
            migrations.RunPython.noop,
        ),
    ]
