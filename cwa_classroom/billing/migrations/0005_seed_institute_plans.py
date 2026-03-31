from django.db import migrations


def seed_plans(apps, schema_editor):
    InstitutePlan = apps.get_model('billing', 'InstitutePlan')
    plans = [
        {
            'name': 'Basic',
            'slug': 'basic',
            'price': 89.00,
            'class_limit': 5,
            'student_limit': 100,
            'invoice_limit_yearly': 500,
            'extra_invoice_rate': 0.30,
            'trial_days': 14,
            'order': 1,
        },
        {
            'name': 'Silver',
            'slug': 'silver',
            'price': 129.00,
            'class_limit': 10,
            'student_limit': 200,
            'invoice_limit_yearly': 750,
            'extra_invoice_rate': 0.25,
            'trial_days': 14,
            'order': 2,
        },
        {
            'name': 'Gold',
            'slug': 'gold',
            'price': 159.00,
            'class_limit': 15,
            'student_limit': 300,
            'invoice_limit_yearly': 1000,
            'extra_invoice_rate': 0.20,
            'trial_days': 14,
            'order': 3,
        },
        {
            'name': 'Platinum',
            'slug': 'platinum',
            'price': 189.00,
            'class_limit': 20,
            'student_limit': 400,
            'invoice_limit_yearly': 2000,
            'extra_invoice_rate': 0.15,
            'trial_days': 14,
            'order': 4,
        },
    ]
    for plan_data in plans:
        InstitutePlan.objects.get_or_create(
            slug=plan_data['slug'],
            defaults=plan_data,
        )


def remove_plans(apps, schema_editor):
    InstitutePlan = apps.get_model('billing', 'InstitutePlan')
    InstitutePlan.objects.filter(
        slug__in=['basic', 'silver', 'gold', 'platinum'],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_institute_plans'),
    ]

    operations = [
        migrations.RunPython(seed_plans, remove_plans),
    ]
