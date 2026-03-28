"""
Migration 0013: Shorten StudentFinalAnswer index names to ≤ 30 characters.

Django enforces a 30-character limit on named indexes (models.E034).
Migration 0010 Step 6 created two indexes whose names exceed this limit:

  maths_sfa_student_topic_level_idx         (34 chars)  →  maths_sfa_topic_level_idx     (25 chars)
  maths_sfa_student_topic_level_attempt_idx (42 chars)  →  maths_sfa_topic_level_att_idx (29 chars)

Strategy — SeparateDatabaseAndState:
  • DB side: guarded RENAME INDEX (MySQL 5.7+).  Checks information_schema first
    so the operation is idempotent — safe if a prior partial run already renamed,
    or on a fresh DB where the long-named index was never created.
  • State side: RemoveIndex (old name) + AddIndex (new short name).
"""
from django.db import migrations, models


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _rename_long_sfa_indexes(apps, schema_editor):
    """
    Rename over-long SFA indexes using MySQL RENAME INDEX if they exist.
    No-op when the old name is already absent (idempotent).
    """
    renames = [
        (
            'maths_sfa_student_topic_level_idx',
            'maths_sfa_topic_level_idx',
        ),
        (
            'maths_sfa_student_topic_level_attempt_idx',
            'maths_sfa_topic_level_att_idx',
        ),
    ]
    db_name = schema_editor.connection.settings_dict['NAME']
    with schema_editor.connection.cursor() as cursor:
        for old_name, new_name in renames:
            # Check whether the old-named index still exists
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = %s "
                "  AND table_name = 'maths_studentfinalanswer' "
                "  AND index_name = %s",
                [db_name, old_name],
            )
            if cursor.fetchone()[0] == 0:
                continue  # Already renamed or never created — skip
            cursor.execute(
                f"ALTER TABLE `maths_studentfinalanswer` "
                f"RENAME INDEX `{old_name}` TO `{new_name}`"
            )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ("maths", "0012_reconcile_classroom_fk_attributes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # DB side: rename in place (no DROP/CREATE — keeps the data hot)
            database_operations=[
                migrations.RunPython(
                    _rename_long_sfa_indexes,
                    migrations.RunPython.noop,
                ),
            ],
            # State side: update the migration graph to use the short names
            state_operations=[
                migrations.RemoveIndex(
                    model_name="studentfinalanswer",
                    name="maths_sfa_student_topic_level_idx",
                ),
                migrations.AddIndex(
                    model_name="studentfinalanswer",
                    index=models.Index(
                        fields=["student", "topic", "level"],
                        name="maths_sfa_topic_level_idx",
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="studentfinalanswer",
                    name="maths_sfa_student_topic_level_attempt_idx",
                ),
                migrations.AddIndex(
                    model_name="studentfinalanswer",
                    index=models.Index(
                        fields=["student", "topic", "level", "attempt_number"],
                        name="maths_sfa_topic_level_att_idx",
                    ),
                ),
            ],
        ),
    ]
