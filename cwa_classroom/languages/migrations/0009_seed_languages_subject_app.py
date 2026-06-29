"""
Data migration: add the Languages SubjectApp record so the Languages card
appears on the Wizards Learning Hub automatically.

Lives in the ``languages`` app (not ``classroom``) so it travels with the
languages feature as a unit through dev → test → prod, avoiding a classroom
migration-number collision on promotion. Depends on classroom 0105 (common to
dev/test/main) purely to guarantee the SubjectApp model exists before we write
to it — that dependency can never dangle during promotion.

Mirrors classroom/migrations/0087_add_coding_subject_app.py.
"""
from django.db import migrations


def add_languages_subject_app(apps, schema_editor):
    SubjectApp = apps.get_model('classroom', 'SubjectApp')
    # Upsert — safe to run multiple times.
    SubjectApp.objects.update_or_create(
        slug='languages',
        defaults={
            'name': 'Languages',
            'description': 'Practice reading, writing, and phonics for English, Sinhala, Tamil and more.',
            'icon_name': 'language',
            'external_url': '/languages/',
            'is_active': True,
            'is_coming_soon': False,
            'order': 3,           # Maths=1, Coding=2, Languages=3
            'color': '#0891b2',   # cyan-600
        },
    )


def remove_languages_subject_app(apps, schema_editor):
    SubjectApp = apps.get_model('classroom', 'SubjectApp')
    SubjectApp.objects.filter(slug='languages').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0008_cpp308_student_answer_updated_at'),
        ('classroom', '0105_school_subscription_discount_code'),
    ]

    operations = [
        migrations.RunPython(add_languages_subject_app, remove_languages_subject_app),
    ]
