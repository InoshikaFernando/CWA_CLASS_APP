from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0096_perf_composite_indexes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailQueue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recipient_email', models.EmailField()),
                ('subject', models.CharField(max_length=300)),
                ('from_email', models.EmailField()),
                ('html_content', models.TextField()),
                ('text_content', models.TextField(blank=True)),
                ('cc', models.JSONField(blank=True, default=list)),
                ('reply_to', models.JSONField(blank=True, default=list)),
                ('notification_type', models.CharField(blank=True, max_length=30)),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')],
                    default='pending', max_length=10,
                )),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('recipient', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='queued_emails',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('campaign', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='queued_emails',
                    to='classroom.emailcampaign',
                )),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
    ]
