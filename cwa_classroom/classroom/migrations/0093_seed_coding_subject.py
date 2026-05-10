"""
Data migration: ensure a global ``classroom.Subject`` row for Coding exists.

Phase 1 of the subject-plugin refactor treats ``classroom.Subject`` as the
canonical list of subjects. Until now only Mathematics had a global Subject
row (seeded by 0006_seed_topic_strands); Coding only had a ``SubjectApp``
hub tile (0087_add_coding_subject_app).

Creating this row is what makes Coding appear on the admin Department edit
page (``DepartmentEditView._get_subjects`` filters ``school__isnull=True``),
and it is the slug the Coding ``SubjectPlugin`` binds to.

Idempotent — uses ``get_or_create``.
"""
from django.db import migrations


def add_coding_subject(apps, schema_editor):
    Subject = apps.get_model('classroom', 'Subject')
    Subject.objects.get_or_create(
        slug='coding',
        school=None,
        defaults={
            'name': 'Coding',
            'is_active': True,
            'order': 2,
        },
    )


def remove_coding_subject(apps, schema_editor):
    Subject = apps.get_model('classroom', 'Subject')
    # Only remove the global row — never touch school-scoped Coding subjects
    Subject.objects.filter(slug='coding', school=None).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0092_merge_20260420_1156'),
    ]

    operations = [
        migrations.RunPython(add_coding_subject, remove_coding_subject),
    ]
