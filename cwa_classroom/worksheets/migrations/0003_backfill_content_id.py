"""
Backfill WorksheetQuestion.content_id from the existing question FK, then add
the unique constraint that depends on content_id being populated.

Must run after 0002 (which adds content_id with default=0).
"""
from django.db import migrations, models


def backfill_content_id(apps, schema_editor):
    """Set content_id = question_id for all existing maths WorksheetQuestion rows."""
    WorksheetQuestion = apps.get_model('worksheets', 'WorksheetQuestion')
    rows = WorksheetQuestion.objects.filter(
        question_id__isnull=False,
        content_id=0,
    )
    for wq in rows:
        wq.content_id = wq.question_id
    WorksheetQuestion.objects.bulk_update(rows, ['content_id'])


def reverse_backfill(apps, schema_editor):
    """Reset content_id back to 0 (for migration reversal)."""
    WorksheetQuestion = apps.get_model('worksheets', 'WorksheetQuestion')
    WorksheetQuestion.objects.filter(subject_slug='mathematics').update(content_id=0)


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0002_add_subject_slug_content_id_answer_data'),
    ]

    operations = [
        # 1. Backfill content_id so all existing rows have a valid value.
        migrations.RunPython(backfill_content_id, reverse_code=reverse_backfill),
        # 2. Now safe to add the unique constraint.
        migrations.AddConstraint(
            model_name='worksheetquestion',
            constraint=models.UniqueConstraint(
                fields=('worksheet', 'subject_slug', 'content_id'),
                name='unique_worksheet_question_content',
            ),
        ),
    ]
