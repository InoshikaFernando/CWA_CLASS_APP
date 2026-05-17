# Rewritten to be fully idempotent (safe to re-run after partial failure).
#
# History of failures on the test server:
#   - Attempt 1: AlterUniqueTogether ran, dropped old unique, created standalone
#                FK index on submission_id, then failed on new unique (duplicate
#                content_id=0 data).
#   - Attempt 2: Re-ran AlterUniqueTogether(set()), tried to create FK index
#                again → OperationalError 1061 (duplicate key name).
#   - Attempt 3: RunPython idempotent approach, but MySQL error 1553:
#                "Cannot drop index: needed in a foreign key constraint" —
#                the old unique was the ONLY index on submission_id so MySQL
#                refuses to drop it until a replacement FK index exists.
#
# Fix: before dropping the old unique index, ensure a standalone index on
# submission_id exists (creating it if needed). Then the DROP succeeds.
# Every step checks information_schema before acting, making this safe to
# re-run from any partial state.
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
        #
        # MySQL error 1553: you cannot drop a unique index that is the ONLY
        # index covering a FK column until a replacement index exists.
        # submission_id is a FK → worksheets_worksheetsubmission.id, so we
        # must create a standalone index on submission_id first (if needed).
        c.execute(
            """SELECT CONSTRAINT_NAME
               FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = %s
               AND CONSTRAINT_TYPE = 'UNIQUE'""",
            [TABLE],
        )
        old_uniques = [
            name for (name,) in c.fetchall()
            if 'subject_sl' not in name and 'content_id' not in name
        ]
        for name in old_uniques:
            # Check whether any index OTHER than this unique already covers
            # submission_id as its leading column.
            c.execute(
                """SELECT COUNT(*) FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = %s
                   AND COLUMN_NAME = 'submission_id'
                   AND SEQ_IN_INDEX = 1
                   AND INDEX_NAME != %s""",
                [TABLE, name],
            )
            if c.fetchone()[0] == 0:
                # No other index leads with submission_id — create one so
                # MySQL can maintain the FK after we drop the unique.
                c.execute(
                    f'CREATE INDEX `{TABLE}_submission_id_fk_idx`'
                    f' ON `{TABLE}` (`submission_id`)'
                )
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
        #
        # MySQL 8 error 3780: MODIFY COLUMN must use the exact same base type
        # as the referenced column or MySQL rejects the FK as incompatible.
        # Read COLUMN_TYPE from information_schema (e.g. 'bigint') and reuse
        # it — only the NOT NULL → NULL change is needed.
        c.execute(
            """SELECT IS_NULLABLE, COLUMN_TYPE
               FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = %s AND COLUMN_NAME = 'question_id'""",
            [TABLE],
        )
        row = c.fetchone()
        if row and row[0] == 'NO':
            col_type = row[1]  # e.g. 'bigint' or 'int'
            c.execute(
                f'ALTER TABLE `{TABLE}` MODIFY COLUMN `question_id` {col_type} NULL'
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
