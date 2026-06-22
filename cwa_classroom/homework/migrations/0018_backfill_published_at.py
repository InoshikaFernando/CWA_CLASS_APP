from django.db import migrations
from django.db.models import F


def backfill_published_at(apps, schema_editor):
    """Treat all pre-existing homework as already published.

    Before this feature every homework was instantly visible to students.
    Student/parent views now gate on ``published_at__isnull=False``, so set
    ``published_at = created_at`` on existing rows to preserve that visibility.
    New rows manage ``published_at`` through the create flow.
    """
    Homework = apps.get_model('homework', 'Homework')
    Homework.objects.filter(published_at__isnull=True).update(published_at=F('created_at'))


def reverse_backfill(apps, schema_editor):
    # No-op: we cannot reliably distinguish backfilled rows from genuinely
    # published ones, and clearing published_at would hide live homework.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0017_homework_publish_at_homework_published_at'),
    ]

    operations = [
        migrations.RunPython(backfill_published_at, reverse_backfill),
    ]
