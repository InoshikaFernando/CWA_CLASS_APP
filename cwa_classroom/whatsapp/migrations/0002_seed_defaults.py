"""Seed the inert defaults: a disabled global config and the two homework
templates marked inactive (until approved in Meta). Idempotent."""
from django.db import migrations


def seed(apps, schema_editor):
    WhatsAppConfig = apps.get_model('whatsapp', 'WhatsAppConfig')
    WhatsAppTemplate = apps.get_model('whatsapp', 'WhatsAppTemplate')

    if not WhatsAppConfig.objects.filter(school__isnull=True).exists():
        WhatsAppConfig.objects.create(
            school=None,
            is_enabled=False,
            notify_on_publish=True,
            notify_on_submission=True,
        )

    templates = [
        {
            'key': 'homework_published',
            'meta_template_name': 'homework_published',
            'body_param_order': ['homework_title', 'class_name', 'due_date'],
        },
        {
            'key': 'homework_result',
            'meta_template_name': 'homework_result',
            'body_param_order': ['student_name', 'homework_title', 'score', 'total'],
        },
    ]
    for t in templates:
        WhatsAppTemplate.objects.get_or_create(
            key=t['key'],
            defaults={
                'meta_template_name': t['meta_template_name'],
                'language_code': 'en',
                'category': 'utility',
                'is_active': False,
                'body_param_order': t['body_param_order'],
            },
        )


def unseed(apps, schema_editor):
    WhatsAppTemplate = apps.get_model('whatsapp', 'WhatsAppTemplate')
    WhatsAppConfig = apps.get_model('whatsapp', 'WhatsAppConfig')
    WhatsAppTemplate.objects.filter(
        key__in=['homework_published', 'homework_result']).delete()
    WhatsAppConfig.objects.filter(school__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('whatsapp', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
