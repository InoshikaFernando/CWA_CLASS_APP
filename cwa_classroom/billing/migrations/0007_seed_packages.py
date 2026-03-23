from django.db import migrations


def seed_packages(apps, schema_editor):
    Package = apps.get_model('billing', 'Package')
    packages = [
        {
            'name': 'Free',
            'class_limit': 1,
            'price': 0.00,
            'trial_days': 0,
            'order': 1,
        },
        {
            'name': 'Basic',
            'class_limit': 3,
            'price': 9.99,
            'trial_days': 14,
            'order': 2,
        },
        {
            'name': 'Standard',
            'class_limit': 5,
            'price': 19.99,
            'trial_days': 14,
            'order': 3,
        },
        {
            'name': 'Premium',
            'class_limit': 0,
            'price': 29.99,
            'trial_days': 14,
            'order': 4,
        },
    ]
    for pkg_data in packages:
        Package.objects.get_or_create(
            name=pkg_data['name'],
            defaults=pkg_data,
        )


def remove_packages(apps, schema_editor):
    Package = apps.get_model('billing', 'Package')
    Package.objects.filter(
        name__in=['Free', 'Basic', 'Standard', 'Premium'],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0006_stripe_events'),
    ]

    operations = [
        migrations.RunPython(seed_packages, remove_packages),
    ]
