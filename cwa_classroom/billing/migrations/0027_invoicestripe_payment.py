from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0026_platinum_unlimited'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InvoiceStripePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_charged', models.DecimalField(decimal_places=2, max_digits=10)),
                ('amount_applied', models.DecimalField(decimal_places=2, max_digits=10)),
                ('stripe_fee', models.DecimalField(decimal_places=2, max_digits=8)),
                ('currency', models.CharField(default='nzd', max_length=10)),
                ('stripe_checkout_session_id', models.CharField(blank=True, db_index=True, max_length=200)),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('succeeded', 'Succeeded'), ('failed', 'Failed'), ('expired', 'Expired')],
                    default='pending',
                    max_length=20,
                )),
                ('invoice_allocations', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('parent', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invoice_stripe_payments',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
