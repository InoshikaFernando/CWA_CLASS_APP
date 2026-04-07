from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('classroom', '0072_term_holidays'),
    ]

    operations = [
        migrations.AddField(
            model_name='absencetoken',
            name='status',
            field=models.CharField(
                choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='absencetoken',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='absencetoken',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='absence_tokens_reviewed',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='absencetoken',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='absencetoken',
            name='rejection_reason',
            field=models.TextField(blank=True),
        ),
    ]
