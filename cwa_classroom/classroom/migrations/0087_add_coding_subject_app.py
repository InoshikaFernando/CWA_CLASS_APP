"""
Data migration: add the Coding SubjectApp record so the Coding card
appears on the Wizards Learning Hub automatically.
"""
from django.db import migrations


def add_coding_subject_app(apps, schema_editor):
    SubjectApp = apps.get_model('classroom', 'SubjectApp')
    # Upsert — safe to run multiple times
    SubjectApp.objects.update_or_create(
        slug='coding',
        defaults={
            'name': 'Coding',
            'description': 'Practice Python, JavaScript, HTML/CSS and Scratch with topic exercises and algorithm challenges.',
            'icon_name': 'code-bracket',
            'external_url': '/coding/',
            'is_active': True,
            'is_coming_soon': False,
            'order': 2,
            'color': '#7c3aed',   # violet-700
        },
    )


def remove_coding_subject_app(apps, schema_editor):
    SubjectApp = apps.get_model('classroom', 'SubjectApp')
    SubjectApp.objects.filter(slug='coding').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0086_merge_20260407_1056'),
    ]

    operations = [
        migrations.RunPython(add_coding_subject_app, remove_coding_subject_app),
    ]