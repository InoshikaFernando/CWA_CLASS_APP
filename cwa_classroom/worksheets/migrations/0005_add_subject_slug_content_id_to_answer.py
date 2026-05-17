# Rewritten to be fully idempotent (safe to re-run after partial failure).
#
# The original auto-generated migration used AlterUniqueTogether which
# triggers Django's MySQL backend to create a replacement FK index before
# dropping the old unique index.  On the test server this caused:
#   - Attempt 1: duplicate-data error adding the new unique constraint
#   - Attempt 2: duplicate-key error creating the FK index (already exists)
#
# Fix: replace all schema operations with RunPython steps that check the
# current DB state via information_schema before acting.  This makes the
# migration safe to re-run regardless of how far the previous attempt got.
#
# Django state is kept in sync via SeparateDatabaseAndState — the state_operations
# tell Django's ORM what the schema looks like; the database_operations are no-ops
# because the RunPython steps handle everything directly.

from django.db import migrations, models
import django.db.models.deletion


def _column_exists(cursor, table, column):
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        [table, column],
    )
    return cursor.fetchone()[0] > 0


def _unique_index_exists(cursor, table, columns_substring):
    """True if there is a unique index whose name contains columns_substring."""
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
           WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = %s
           AND CONSTRAINT_TYPE = 'UNIQUE'
           AND CONSTRAINT_NAME LIKE %s""",
        [table, f'%{columns_substring}%'],
    )
    return cursor.fetchone()[0] > 0


def apply_forward(apps, schema_editor):
    TABLE = 'worksheets_worksheetstudentanswer'
    conn = schema_editor.connection

    with conn.cursor() as c:

        # ── 1. Drop old unique_together (submission, question) if still present ──
        c.execute(
            """SELECT CONSTRAINT_NAME
               FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = %s
               AND CONSTRAINT_TYPE = 'UNIQUE'""",
            [TABLE],
        )
        for (name,) in c.fetchall():
            # Only drop constraints that look like the old (submission, question) one —
            # i.e. NOT the new one we're about to create.
            if 'subject_sl' not in name and 'content_id' not in name:
                c.execute(f'ALTER TABLE `{TABLE}` DROP INDEX `{name}`')

        # ── 2. Add new columns (each idempotent) ─────────────────────────────────

        if not _column_exists(c, TABLE, 'coding_exercise_id'):
            c.execute(
                f'ALTER TABLE `{TABLE}` ADD COLUMN `coding_exercise_id` INT UNSIGNED NULL'
            )
        if not _column_exists(c, TABLE, 'content_id'):
            c.execute(
                f"ALTER TABLE `{TABLE}` ADD COLUMN `content_id` INT UNSIGNED NOT NULL DEFAULT 0"
            )
        if not _column_exists(c, TABLE, 'subject_slug'):
            c.execute(
                f"ALTER TABLE `{TABLE}` ADD COLUMN `subject_slug` VARCHAR(50) NOT NULL DEFAULT 'mathematics'"
            )
            c.execute(
                f'CREATE INDEX `{TABLE}_subject_slug_idx` ON `{TABLE}` (`subject_slug`)'
            )

        # ── 3. Make question_id nullable if it isn't already ────────────────────
        c.execute(
            """SELECT IS_NULLABLE FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = %s AND COLUMN_NAME = 'question_id'""",
            [TABLE],
        )
        row = c.fetchone()
        if row and row[0] == 'NO':
            c.execute(
                f'ALTER TABLE `{TABLE}` MODIFY COLUMN `question_id` INT UNSIGNED NULL'
            )

        # ── 4. Backfill content_id = question_id for all existing maths rows ────
        c.execute(
            f'UPDATE `{TABLE}` SET content_id = question_id '
            f'WHERE question_id IS NOT NULL AND content_id = 0'
        )

        # ── 5. Create new unique constraint if not already present ───────────────
        if not _unique_index_exists(c, TABLE, 'subject_sl'):
            c.execute(
                f"""ALTER TABLE `{TABLE}`
                    ADD UNIQUE KEY
                    `worksheets_worksheetstud_submission_id_subject_sl_445dca9d_uniq`
                    (`submission_id`, `subject_slug`, `content_id`)"""
            )


class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0027_merge_20260511_1752'),
        ('coding', '0017_merge_20260429_2301'),
        ('worksheets', '0004_add_coding_exercise_fk'),
    ]

    operations = [
        # All schema + data work is done in the idempotent RunPython above.
        # SeparateDatabaseAndState keeps Django's ORM state in sync without
        # re-running any DDL that the RunPython already handled.
        migrations.RunPython(apply_forward, migrations.RunPython.noop),

        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(
                    name='worksheetstudentanswer',
                    unique_together=set(),
                ),
                migrations.AddField(
                    model_name='worksheetstudentanswer',
                    name='coding_exercise',
                    field=models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='worksheet_student_answers',
                        to='coding.codingexercise',
                    ),
                ),
                migrations.AddField(
                    model_name='worksheetstudentanswer',
                    name='content_id',
                    field=models.PositiveIntegerField(
                        default=0,
                        help_text='pk of the content row (maths.Question.id, CodingExercise.id, etc.).',
                    ),
                ),
                migrations.AddField(
                    model_name='worksheetstudentanswer',
                    name='subject_slug',
                    field=models.CharField(db_index=True, default='mathematics', max_length=50),
                ),
                migrations.AlterField(
                    model_name='worksheetstudentanswer',
                    name='question',
                    field=models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='worksheet_student_answers',
                        to='maths.question',
                    ),
                ),
                migrations.AlterUniqueTogether(
                    name='worksheetstudentanswer',
                    unique_together={('submission', 'subject_slug', 'content_id')},
                ),
            ],
            database_operations=[],  # all handled by RunPython above
        ),
    ]
