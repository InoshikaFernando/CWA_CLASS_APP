from django.db import migrations


def seed_ai_import_modules(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    modules = [
        {
            'module': 'ai_import_starter',
            'name': 'AI Question Import - Starter',
            'price': 30.00,
        },
        {
            'module': 'ai_import_professional',
            'name': 'AI Question Import - Professional',
            'price': 60.00,
        },
        {
            'module': 'ai_import_enterprise',
            'name': 'AI Question Import - Enterprise',
            'price': 99.00,
        },
    ]
    for m in modules:
        ModuleProduct.objects.get_or_create(
            module=m['module'],
            defaults={'name': m['name'], 'price': m['price']},
        )


def reverse_seed(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleProduct.objects.filter(
        module__in=['ai_import_starter', 'ai_import_professional', 'ai_import_enterprise']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0018_add_promo_code_used_to_subscription'),
    ]

    operations = [
        migrations.RunPython(seed_ai_import_modules, reverse_seed),
    ]
