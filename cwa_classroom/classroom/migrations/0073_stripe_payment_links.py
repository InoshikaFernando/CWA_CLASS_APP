from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0072_term_holidays'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='stripe_payment_link',
            field=models.URLField(
                blank=True,
                help_text='Default Stripe Payment Link for this institute. Parents see a Pay Now button linking here.',
            ),
        ),
        migrations.AddField(
            model_name='department',
            name='stripe_payment_link',
            field=models.URLField(
                blank=True,
                help_text='Stripe Payment Link override for this department. Overrides the institute default.',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='stripe_payment_link',
            field=models.URLField(
                blank=True,
                help_text='Stripe Payment Link override for this invoice. Overrides department and institute defaults.',
            ),
        ),
    ]
