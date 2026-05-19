# Fully idempotent migration — safe to re-run from any partial state.
#
# Uses SET foreign_key_checks = 0 for the entire block so every DROP INDEX
# and MODIFY COLUMN succeeds regardless of FK constraints (bypasses MySQL
# errors 1553 and similar). Error 3780 (FK type mismatch on MODIFY COLUMN)
# is handled separately by reading the actual COLUMN_TYPE from
# information_schema rather than hardcoding a type.
#
# Every DDL step checks information_schema first so re-runs are no-ops.
#
# Django ORM state is kept in sync via SeparateDatabaseAndState —
# state_operations describe the final model shape; database_operations=[]
# because RunPython already handled all DDL.

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
    TABLE = 'worksheets_worksheetstudentanswer'
    conn = schema_editor.connection

    with conn.cursor() as c:

        # Disable FK checks for the whole block.
        # ▸ Bypasses error 1553 ("cannot drop index: needed in FK constraint")
        #   so we can drop the old unique index without first creating a
        #   replacement FK-backing index on submission_id.
        # ▸ MySQL automatically re-enables FK checks when the session ends,
        #   so a mid-migration failure is safe.
        c.execute('SET foreign_key_checks = 0')
        try:

            # Ensure submission_id has a standalone index before dropping the
            # combined unique.  MySQL error 1553 fires structurally (not just
            # as a data-integrity check) when the combined unique is the ONLY
            # index covering submission_id — foreign_key_checks=0 does NOT
            # suppress it.  Once the new (submission, subject_slug, content_id)
            # unique is in place (step 5), this temporary index is redundant
            # because submission_id is its leftmost column.
            if not _index_exists(c, TABLE, f'{TABLE}_submission_id_tmp_idx'):
                c.execute(
                    f'CREATE INDEX `{TABLE}_submission_id_tmp_idx`'
                    f' ON `{TABLE}` (`submission_id`)'
                )

            # ── 1. Drop old unique_together (submission, question) ───────────
            c.execute(
                """SELECT CONSTRAINT_NAME
                   FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = %s
                   AND CONSTRAINT_TYPE = 'UNIQUE'""",
                [TABLE],
            )
            for (name,) in c.fetchall():
                # Drop any unique that isn't our new (submission, subject_slug,
                # content_id) constraint — identified by NOT containing
                # 'subject_sl' or 'content_id' in the auto-generated name.
                if 'subject_sl' not in name and 'content_id' not in name:
                    c.execute(f'ALTER TABLE `{TABLE}` DROP INDEX `{name}`')

            # ── 2. Add new columns (idempotent) ─────────────────────────────
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
            # Index for subject_slug — created separately so a re-run that
            # finds the column already present can still create a missing index.
            if not _index_exists(c, TABLE, f'{TABLE}_subject_slug_idx'):
                c.execute(
                    f'CREATE INDEX `{TABLE}_subject_slug_idx`'
                    f' ON `{TABLE}` (`subject_slug`)'
                )

            # ── 3. Make question_id nullable ─────────────────────────────────
            # Read the actual COLUMN_TYPE (e.g. 'bigint') to avoid MySQL 3780:
            # "Referencing column and referenced column are incompatible."
            # Hardcoding 'INT UNSIGNED' fails when the PK is BIGINT (signed).
            row = _col(c, TABLE, 'question_id')
            if row and row[0] == 'NO':          # IS_NULLABLE == 'NO'
                col_type = row[1]               # e.g. 'bigint'
                c.execute(
                    f'ALTER TABLE `{TABLE}`'
                    f' MODIFY COLUMN `question_id` {col_type} NULL'
                )

            # ── 4. Backfill content_id from question_id ──────────────────────
            c.execute(
                f'UPDATE `{TABLE}`'
                f' SET content_id = question_id'
                f' WHERE question_id IS NOT NULL AND content_id = 0'
            )

            # ── 5. Create new unique constraint ──────────────────────────────
            if not _unique_exists(c, TABLE, 'subject_sl'):
                c.execute(
                    f'ALTER TABLE `{TABLE}`'
                    f' ADD UNIQUE KEY'
                    f' `worksheets_worksheetstud_submission_id_subject_sl_445dca9d_uniq`'
                    f' (`submission_id`, `subject_slug`, `content_id`)'
                )

            # Drop the temporary standalone index — now redundant because the
            # new unique above has submission_id as its leftmost column.
            if _index_exists(c, TABLE, f'{TABLE}_submission_id_tmp_idx'):
                c.execute(
                    f'DROP INDEX `{TABLE}_submission_id_tmp_idx` ON `{TABLE}`'
                )

        finally:
            c.execute('SET foreign_key_checks = 1')


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
