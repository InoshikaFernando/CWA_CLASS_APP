from django.db import migrations


def seed_pages_per_month(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    limits = {
        'ai_import_starter': 300,
        'ai_import_professional': 600,
        'ai_import_enterprise': 1000,
    }
    for module_slug, pages in limits.items():
        ModuleProduct.objects.filter(module=module_slug).update(pages_per_month=pages)


def reverse_seed(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleProduct.objects.filter(
        module__in=['ai_import_starter', 'ai_import_professional', 'ai_import_enterprise']
    ).update(pages_per_month=None)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0030_moduleproduct_pages_per_month'),
    ]

    operations = [
        migrations.RunPython(seed_pages_per_month, reverse_seed),
    ]
