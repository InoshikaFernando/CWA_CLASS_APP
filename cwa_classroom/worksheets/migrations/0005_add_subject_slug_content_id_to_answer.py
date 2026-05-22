# Fully idempotent migration — safe to re-run from any partial state.
#
# Every DDL step checks information_schema first so re-runs are no-ops.
#
# Step 2 creates the new unique (submission_id, subject_slug, content_id)
# BEFORE dropping the old (submission_id, question_id) unique. This gives
# MySQL an alternative backing index for the submission_id FK, so the DROP
# INDEX in step 3 succeeds without needing foreign_key_checks=0 (avoids
# MySQL errors 1553 and similar).
#
# Django ORM state is kept in sync via SeparateDatabaseAndState —
# state_operations describe the final model shape; database_operations=[]
# because RunPython already handled all DDL.
#
# On non-MySQL backends (e.g. SQLite in CI) the RunPython function is a
# no-op — Django's standard migration machinery handles the DDL via the
# SeparateDatabaseAndState state_operations instead.

from django.db import migrations, models
import django.db.models.deletion


# ── Helpers ──────────────────────────────────────────────────────────────────

def _col(cursor, table, column):
    """Return (is_nullable, column_type) for a column, or None if not found."""
    cursor.execute(
        """SELECT IS_NULLABLE, COLUMN_TYPE
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        [table, column],
    )
    return cursor.fetchone()


def _index_exists(cursor, table, index_name):
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = %s AND INDEX_NAME = %s""",
        [table, index_name],
    )
    return cursor.fetchone()[0] > 0


def _unique_exists(cursor, table, name_substr):
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
           WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = %s
           AND CONSTRAINT_TYPE = 'UNIQUE'
           AND CONSTRAINT_NAME LIKE %s""",
        [table, f'%{name_substr}%'],
    )
    return cursor.fetchone()[0] > 0


# ── Forward migration ─────────────────────────────────────────────────────────

def apply_forward(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    TABLE = 'worksheets_worksheetstudentanswer'
    conn = schema_editor.connection

    with conn.cursor() as c:

        # ── 1. Add new columns first (idempotent) ────────────────────────────
        if not _col(c, TABLE, 'coding_exercise_id'):
            c.execute(
                f'ALTER TABLE `{TABLE}`'
                f' ADD COLUMN `coding_exercise_id` bigint NULL'
            )
        if not _col(c, TABLE, 'content_id'):
            c.execute(
                f'ALTER TABLE `{TABLE}`'
                f" ADD COLUMN `content_id` int unsigned NOT NULL DEFAULT 0"
            )
        if not _col(c, TABLE, 'subject_slug'):
            c.execute(
                f'ALTER TABLE `{TABLE}`'
                f" ADD COLUMN `subject_slug` varchar(50) NOT NULL DEFAULT 'mathematics'"
            )
        if not _index_exists(c, TABLE, f'{TABLE}_subject_slug_idx'):
            c.execute(
                f'CREATE INDEX `{TABLE}_subject_slug_idx`'
                f' ON `{TABLE}` (`subject_slug`)'
            )

        # ── 2. Create new unique BEFORE dropping old one ──────────────────────
        # Adding the new unique (submission_id, subject_slug, content_id) first
        # gives MySQL an alternative backing index for the submission_id FK, so
        # the subsequent DROP INDEX in step 3 succeeds without error 1553.
        if not _unique_exists(c, TABLE, 'subject_sl'):
            c.execute(
                f'ALTER TABLE `{TABLE}`'
                f' ADD UNIQUE KEY'
                f' `worksheets_worksheetstud_submission_id_subject_sl_445dca9d_uniq`'
                f' (`submission_id`, `subject_slug`, `content_id`)'
            )

        # ── 3. Drop old unique_together (submission, question) ────────────────
        # Only target the original Django-generated unique that contains
        # 'question' in its name — avoids collateral damage to any other
        # unique constraints added by future migrations.
        c.execute(
            """SELECT CONSTRAINT_NAME
               FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = %s
               AND CONSTRAINT_TYPE = 'UNIQUE'""",
            [TABLE],
        )
        for (name,) in c.fetchall():
            if 'question' in name and 'subject_sl' not in name:
                c.execute(f'ALTER TABLE `{TABLE}` DROP INDEX `{name}`')

        # ── 4. Make question_id nullable ──────────────────────────────────────
        # Read actual COLUMN_TYPE to avoid MySQL 3780 on MODIFY COLUMN.
        row = _col(c, TABLE, 'question_id')
        if row and row[0] == 'NO':
            col_type = row[1]
            c.execute(
                f'ALTER TABLE `{TABLE}`'
                f' MODIFY COLUMN `question_id` {col_type} NULL'
            )

        # ── 5. Backfill content_id from question_id ───────────────────────────
        c.execute(
            f'UPDATE `{TABLE}`'
            f' SET content_id = question_id'
            f' WHERE question_id IS NOT NULL AND content_id = 0'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0027_merge_20260511_1752'),
        ('coding', '0017_merge_20260429_2301'),
        ('worksheets', '0004_add_coding_exercise_fk'),
    ]

    operations = [
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
