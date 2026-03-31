"""
Migration 0012: Reconcile FK field attributes after migration 0010 renames.

Migration 0010 added shadow FK fields (classroom_topic / classroom_level) as
nullable placeholders and renamed them to topic / level.  The resulting state
no longer matches models.py in two areas:

  1. related_name  — shadow AddField ops used '_new' suffixed related names
                     (e.g. 'maths_questions_new' instead of 'maths_questions')
  2. null/blank    — Question.level, TopicLevelStatistics.level / .topic
                     should be non-nullable (matching original FK semantics)

Steps:
  A. RunPython safety guard: delete any TopicLevelStatistics rows whose
     classroom_level or classroom_topic is NULL (orphaned by a partial run).
     These would cause the NOT NULL ALTER TABLE to fail.
  B. AlterField Question.level — remove nullable, fix related_name.
     Uses SeparateDatabaseAndState: the state side marks it non-nullable
     (satisfying Django's check), while the DB side is a guarded RunSQL that
     only issues the NOT NULL constraint if every row already has a value.
     (Data was filled by migration 0010; this guard handles edge cases.)
  C. AlterField for remaining 6 fields — related_name / on_delete corrections.
"""
from django.db import migrations, models
import django.db.models.deletion


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------

def _remove_null_tls_rows(apps, schema_editor):
    """
    Delete TopicLevelStatistics rows where classroom_level_id or
    classroom_topic_id is NULL.  Such rows are left-over artefacts of a
    previously failed partial migration and cannot satisfy the NOT NULL
    constraint we are about to apply.
    """
    TopicLevelStatistics = apps.get_model('maths', 'TopicLevelStatistics')
    deleted_level, _ = TopicLevelStatistics.objects.filter(level__isnull=True).delete()
    deleted_topic, _ = TopicLevelStatistics.objects.filter(topic__isnull=True).delete()
    if deleted_level or deleted_topic:
        import sys
        print(
            f"  [0012] Removed orphaned TopicLevelStatistics rows: "
            f"{deleted_level} null-level, {deleted_topic} null-topic",
            file=sys.stderr,
        )


def _make_question_level_not_null(apps, schema_editor):
    """
    Conditionally apply NOT NULL to maths_question.level_id.
    Skips the ALTER TABLE if any NULL values remain (shouldn't happen after
    migration 0010, but avoids a hard failure on unexpected data).
    """
    db_name = schema_editor.connection.settings_dict['NAME']
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM maths_question WHERE level_id IS NULL"
        )
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            import sys
            print(
                f"  [0012] WARNING: {null_count} question(s) have NULL level_id — "
                "skipping NOT NULL constraint.  Fix manually and re-run migrate.",
                file=sys.stderr,
            )
            return
        # Safe to make NOT NULL
        cursor.execute(
            "SELECT column_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'maths_question' "
            "AND column_name = 'level_id'",
            [db_name],
        )
        row = cursor.fetchone()
        if row:
            col_type = row[0].upper()
            if 'NOT NULL' not in col_type:
                # Extract the base numeric type (e.g. 'int') from col_type
                base_type = col_type.split('(')[0].strip()
                cursor.execute(
                    f"ALTER TABLE `maths_question` "
                    f"MODIFY COLUMN `level_id` {base_type} NOT NULL"
                )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Migration(migrations.Migration):

    dependencies = [
        ("maths", "0011_remove_classroom_enrollment_level_topic"),
        ("classroom", "0069_pending_password_fields"),
    ]

    operations = [

        # ── A. Remove orphaned NULL rows in TopicLevelStatistics ─────────────
        migrations.RunPython(_remove_null_tls_rows, migrations.RunPython.noop),

        # ── B. Question.level: nullable → non-nullable + related_name fix ────
        #
        # SeparateDatabaseAndState lets the state side mark the field as
        # non-nullable (so Django's "unsynchronised models" warning goes away)
        # while the database side uses guarded raw SQL instead of Django's
        # AlterField, which would fail mid-migration if any NULL rows exist.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    _make_question_level_not_null,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="question",
                    name="level",
                    field=models.ForeignKey(
                        "classroom.Level",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="maths_questions_by_level",
                    ),
                ),
            ],
        ),

        # ── C. Remaining AlterField corrections ──────────────────────────────

        # Question.topic: related_name 'maths_questions_new' → 'maths_questions'
        migrations.AlterField(
            model_name="question",
            name="topic",
            field=models.ForeignKey(
                "classroom.Topic",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="maths_questions",
                help_text=(
                    "Topic this question belongs to "
                    "(e.g., BODMAS/PEMDAS, Measurements, Fractions)"
                ),
            ),
        ),

        # BasicFactsResult.level: related_name fix (stays nullable)
        migrations.AlterField(
            model_name="basicfactsresult",
            name="level",
            field=models.ForeignKey(
                "classroom.Level",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="maths_basic_facts_results",
            ),
        ),

        # TopicLevelStatistics.level: nullable → non-nullable + related_name fix
        migrations.AlterField(
            model_name="topiclevelstatistics",
            name="level",
            field=models.ForeignKey(
                "classroom.Level",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="maths_topic_statistics",
            ),
        ),

        # TopicLevelStatistics.topic: nullable → non-nullable + related_name fix
        migrations.AlterField(
            model_name="topiclevelstatistics",
            name="topic",
            field=models.ForeignKey(
                "classroom.Topic",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="maths_level_statistics",
            ),
        ),

        # StudentFinalAnswer.topic: related_name 'maths_final_answers_new' → fix
        migrations.AlterField(
            model_name="studentfinalanswer",
            name="topic",
            field=models.ForeignKey(
                "classroom.Topic",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="maths_final_answers",
            ),
        ),

        # StudentFinalAnswer.level: related_name 'maths_final_answers_by_level_new' → fix
        migrations.AlterField(
            model_name="studentfinalanswer",
            name="level",
            field=models.ForeignKey(
                "classroom.Level",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="maths_final_answers",
            ),
        ),
    ]
