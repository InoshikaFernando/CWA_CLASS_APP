"""
Migration 0014: Remove three auto-generated index names from migration state.

When models.py gained explicit ``name=`` on indexes for StudentFinalAnswer
and TopicLevelStatistics, Django detected that the migration state still
contained the old auto-generated names:

  maths_stude_student_ad30a8_idx  — StudentFinalAnswer (student, topic, level)
  maths_stude_student_2e8b01_idx  — StudentFinalAnswer (student, topic, level, attempt_number)
  maths_topic_level_i_267d9e_idx  — TopicLevelStatistics (level, topic)

Strategy — SeparateDatabaseAndState:
  • State side : RemoveIndex the three auto-named entries so the graph
                 matches models.py (which uses explicit short names).
  • DB side    : guarded DROP INDEX — checks information_schema first so
                 the operation is idempotent.  On a fresh DB these indexes
                 never existed (only the explicit-named versions were
                 created by migration 0010 / renamed by 0013).
"""
from django.db import migrations, models


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _drop_auto_indexes_if_exist(apps, schema_editor):
    """
    Drop the three auto-named indexes from the DB if they still exist.
    No-op when they are absent (idempotent).
    """
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
        migrations.SeparateDatabaseAndState(
            # DB side: drop only if present
            database_operations=[
                migrations.RunPython(
                    _drop_auto_indexes_if_exist,
                    migrations.RunPython.noop,
                ),
            ],
            # State side: remove the three auto-named entries
            state_operations=[
                migrations.RemoveIndex(
                    model_name="studentfinalanswer",
                    name="maths_stude_student_ad30a8_idx",
                ),
                migrations.RemoveIndex(
                    model_name="studentfinalanswer",
                    name="maths_stude_student_2e8b01_idx",
                ),
                migrations.RemoveIndex(
                    model_name="topiclevelstatistics",
                    name="maths_topic_level_i_267d9e_idx",
                ),
            ],
        ),
    ]
