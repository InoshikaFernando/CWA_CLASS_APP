"""
Migration: create strand topics (Algebra, Geometry, etc.) and assign
existing flat subtopics to their correct parent strand, based on the
canonical TOPIC_MAPPING used throughout the app.
"""
from django.db import migrations

TOPIC_MAPPING = {
    "Algebra":     ["BODMAS", "Integers", "Factors"],
    "Geometry":    ["Angles", "Trigonometry"],
    "Measurement": ["Measurements", "Date and Time"],
    "Number":      ["Whole Numbers", "Place Values", "Fractions",
                    "Multiplication", "Division", "Finance"],
    "Space":       [],
    "Statistics":  [],
}


def seed_topic_strands(apps, schema_editor):
    from django.utils.text import slugify

    Subject = apps.get_model('classroom', 'Subject')
    Topic = apps.get_model('classroom', 'Topic')

    maths, _ = Subject.objects.get_or_create(
        name='Mathematics',
        defaults={'slug': 'mathematics', 'is_active': True},
    )

    for strand_order, (strand_name, subtopic_names) in enumerate(TOPIC_MAPPING.items()):
        strand, _ = Topic.objects.get_or_create(
            subject=maths,
            slug=slugify(strand_name),
            defaults={
                'name': strand_name,
                'order': strand_order,
                'is_active': True,
                'parent': None,
            },
        )
        # Ensure existing strand topic has no parent and is named correctly
        if strand.parent_id is not None:
            strand.parent = None
            strand.save()

        for sub_order, sub_name in enumerate(subtopic_names):
            subtopic, _ = Topic.objects.get_or_create(
                subject=maths,
                slug=slugify(sub_name),
                defaults={
                    'name': sub_name,
                    'order': sub_order,
                    'is_active': True,
                    'parent': strand,
                },
            )
            if subtopic.parent_id != strand.id:
                subtopic.parent = strand
                subtopic.order = sub_order
                subtopic.save()


def reverse_seed_topic_strands(apps, schema_editor):
    # Remove parent from subtopics (make them flat again), leave strands
    from django.utils.text import slugify
    Subject = apps.get_model('classroom', 'Subject')
    Topic = apps.get_model('classroom', 'Topic')

    maths = Subject.objects.filter(name='Mathematics').first()
    if not maths:
        return

    for strand_name, subtopic_names in TOPIC_MAPPING.items():
        for sub_name in subtopic_names:
            Topic.objects.filter(
                subject=maths, slug=slugify(sub_name)
            ).update(parent=None)

        Topic.objects.filter(
            subject=maths, slug=slugify(strand_name), parent=None
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0005_seed_classrooms'),
    ]

    operations = [
        migrations.RunPython(seed_topic_strands, reverse_seed_topic_strands),
    ]
