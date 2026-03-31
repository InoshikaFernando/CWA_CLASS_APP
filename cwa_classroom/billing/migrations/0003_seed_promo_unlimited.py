from django.db import migrations


def seed_promo_and_assign_students(apps, schema_editor):
    PromoCode = apps.get_model('billing', 'PromoCode')
    Role = apps.get_model('accounts', 'Role')
    CustomUser = apps.get_model('accounts', 'CustomUser')

    # Create (or get) the unlimited promo code
    promo, _ = PromoCode.objects.get_or_create(
        code='UNLIMITED2026',
        defaults={
            'description': 'Unlimited class access',
            'class_limit': 0,
            'is_active': True,
        },
    )

    # Find all individual_student users and assign the promo
    try:
        role = Role.objects.get(name='individual_student')
    except Role.DoesNotExist:
        return

    individual_students = CustomUser.objects.filter(
        user_roles__role=role
    )
    for student in individual_students:
        promo.redeemed_by.add(student)


def reverse_seed(apps, schema_editor):
    PromoCode = apps.get_model('billing', 'PromoCode')
    PromoCode.objects.filter(code='UNLIMITED2026').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_promo_code'),
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_promo_and_assign_students, reverse_seed),
    ]
