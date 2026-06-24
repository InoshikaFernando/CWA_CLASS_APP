"""
Data migration: seed Subject(slug='languages') and seed initial Language records
(English, Sinhala, Tamil) for CPP-309.
"""

from django.db import migrations


def seed_data(apps, schema_editor):
    Subject = apps.get_model('classroom', 'Subject')
    Language = apps.get_model('languages', 'Language')

    Subject.objects.get_or_create(
        slug='languages',
        defaults={'name': 'Languages', 'order': 30, 'is_active': True},
    )

    for order, (name, code, script) in enumerate([
        ('English', 'en', 'latin'),
        ('Sinhala', 'si', 'sinhala'),
        ('Tamil', 'ta', 'tamil'),
    ], start=1):
        Language.objects.get_or_create(
            code=code,
            defaults={'name': name, 'script_type': script, 'is_active': True, 'order': order},
        )


def unseed_data(apps, schema_editor):
    Subject = apps.get_model('classroom', 'Subject')
    Language = apps.get_model('languages', 'Language')
    Subject.objects.filter(slug='languages').delete()
    Language.objects.filter(code__in=['en', 'si', 'ta']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0100_cpp297_expense_model'),
        ('languages', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_code=unseed_data),
    ]
