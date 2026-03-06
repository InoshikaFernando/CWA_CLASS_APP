"""
Migration: assign subtopics to their year levels based on the canonical
topic-level map used by setup_dev. Safe to run on a DB that already has
some associations — topic.levels.add() is idempotent.
"""
from django.db import migrations

# subtopic name → list of year level numbers
TOPIC_LEVEL_MAP = {
    'Measurements':   [2, 3, 5, 6, 7],
    'Whole Numbers':  [6],
    'Factors':        [6, 7, 8],
    'Angles':         [6],
    'Place Values':   [2, 4],
    'Fractions':      [3, 4, 7, 8],
    'BODMAS':         [5, 6, 7],
    'Date and Time':  [3],
    'Finance':        [3],
    'Integers':       [4, 7, 8],
    'Trigonometry':   [8],
    'Multiplication': [1, 2, 3, 4],
    'Division':       [1, 2, 3, 4],
}


def seed_topic_level_links(apps, schema_editor):
    from django.utils.text import slugify

    Subject = apps.get_model('classroom', 'Subject')
    Topic = apps.get_model('classroom', 'Topic')
    Level = apps.get_model('classroom', 'Level')

    maths = Subject.objects.filter(name='Mathematics').first()
    if not maths:
        return

    for sub_name, year_numbers in TOPIC_LEVEL_MAP.items():
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slugify(sub_name))
        except Topic.DoesNotExist:
            continue
        for year in year_numbers:
            level = Level.objects.filter(level_number=year).first()
            if level:
                subtopic.levels.add(level)


def reverse_seed_topic_level_links(apps, schema_editor):
    from django.utils.text import slugify

    Subject = apps.get_model('classroom', 'Subject')
    Topic = apps.get_model('classroom', 'Topic')
    Level = apps.get_model('classroom', 'Level')

    maths = Subject.objects.filter(name='Mathematics').first()
    if not maths:
        return

    for sub_name, year_numbers in TOPIC_LEVEL_MAP.items():
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slugify(sub_name))
        except Topic.DoesNotExist:
            continue
        for year in year_numbers:
            level = Level.objects.filter(level_number=year).first()
            if level:
                subtopic.levels.remove(level)


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0006_seed_topic_strands'),
    ]

    operations = [
        migrations.RunPython(seed_topic_level_links, reverse_seed_topic_level_links),
    ]
