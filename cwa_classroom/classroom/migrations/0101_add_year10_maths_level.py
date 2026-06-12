"""
Add a Year 10 curriculum level for Mathematics and link the top-level
strands (Algebra, Geometry, Measurement, Number, Statistics) to it as
placeholders. Subtopics/questions are added later via the admin.

Year levels are level_number < 100 (Basic Facts are >= 100), so Year 10
slots in alongside Year 1-9 created by setup_data / migration 0005.
"""
from django.db import migrations

STRAND_NAMES = ['Algebra', 'Geometry', 'Measurement', 'Number', 'Statistics']


def add_year10(apps, schema_editor):
    Level = apps.get_model('classroom', 'Level')
    Subject = apps.get_model('classroom', 'Subject')
    Topic = apps.get_model('classroom', 'Topic')

    maths = (
        Subject.objects.filter(slug='mathematics').first()
        or Subject.objects.filter(name='Mathematics').first()
    )
    if maths is None:
        # No Mathematics subject yet (e.g. a fresh test DB before seeding) —
        # nothing to attach Year 10 to.
        return

    level, _ = Level.objects.get_or_create(
        level_number=10,
        defaults={'display_name': 'Year 10', 'subject': maths},
    )
    if level.subject_id is None:
        level.subject = maths
        level.save(update_fields=['subject'])

    strands = Topic.objects.filter(
        subject=maths, parent__isnull=True, name__in=STRAND_NAMES,
    )
    for strand in strands:
        strand.levels.add(level)


def remove_year10(apps, schema_editor):
    Level = apps.get_model('classroom', 'Level')
    # M2M links (classroom_topic_levels) are removed automatically when the
    # Level row is deleted.
    Level.objects.filter(level_number=10).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0100_cpp297_expense_model'),
    ]

    operations = [
        migrations.RunPython(add_year10, remove_year10),
    ]
