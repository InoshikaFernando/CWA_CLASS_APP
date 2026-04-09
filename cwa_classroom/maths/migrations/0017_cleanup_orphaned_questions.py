"""
Migration 0017: Delete Question records that have NULL level_id or NULL topic_id.

These ghost records were created on fresh installations by seed migrations
(classroom/0008–0031) that incorrectly referenced apps.get_model('quiz', 'Question')
instead of apps.get_model('maths', 'Question').  The quiz.Question historical model
used a nullable level field, so questions were inserted without a level or topic.

On environments where the seed migrations ran correctly (e.g. production), this
migration is a safe no-op — no rows match the filter.
"""
from django.db import migrations


def delete_orphaned_questions(apps, schema_editor):
    # Use raw SQL — the ORM skips isnull filters on columns declared non-nullable
    # in the current model, even though the DB may still hold legacy NULL values.
    db = schema_editor.connection
    with db.cursor() as cursor:
        cursor.execute(
            'SELECT id FROM maths_question WHERE level_id IS NULL OR topic_id IS NULL'
        )
        orphaned_ids = [row[0] for row in cursor.fetchall()]

    if not orphaned_ids:
        return

    ids_sql = ','.join(str(i) for i in orphaned_ids)

    # Delete in FK dependency order (deepest children first)
    with db.cursor() as cursor:
        # 1. homework answers that reference orphaned questions/answers
        cursor.execute(
            f'DELETE FROM homework_homeworkstudentanswer WHERE question_id IN ({ids_sql})'
        )
        # 2. student quiz answers referencing orphaned questions/answers
        cursor.execute(
            f'DELETE FROM maths_studentanswer WHERE question_id IN ({ids_sql})'
        )
        # 3. homework question assignments
        cursor.execute(
            f'DELETE FROM homework_homeworkquestion WHERE question_id IN ({ids_sql})'
        )
        # 4. answer choices for orphaned questions
        cursor.execute(f'DELETE FROM maths_answer WHERE question_id IN ({ids_sql})')
        ans_deleted = cursor.rowcount
        # 5. the orphaned questions themselves
        cursor.execute(f'DELETE FROM maths_question WHERE id IN ({ids_sql})')
        q_deleted = cursor.rowcount

    print(f'\n  Removed {q_deleted} orphaned Questions '
          f'and {ans_deleted} associated Answers (NULL level or topic).')


class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0016_add_video_and_answer_image'),
        # Ensure all seed migrations have run before we clean up
        ('classroom', '0031_seed_year8_fractions'),
    ]

    operations = [
        migrations.RunPython(
            delete_orphaned_questions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
