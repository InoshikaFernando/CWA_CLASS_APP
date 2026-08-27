from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0104_classroom_whatsapp_group_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduledMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(max_length=255)),
                ('body_html', models.TextField(blank=True)),
                ('channel', models.CharField(default='email', max_length=10)),
                ('recipients_to', models.JSONField(default=list)),
                ('recipients_cc', models.JSONField(default=list)),
                ('recipients_bcc', models.JSONField(default=list)),
                ('frequency', models.CharField(
                    choices=[('now', 'Send Now'), ('once', 'One Time'), ('weekly', 'Weekly'), ('monthly', 'Monthly')],
                    default='now',
                    max_length=10,
                )),
                ('scheduled_at', models.DateTimeField(blank=True, null=True)),
                ('send_time', models.TimeField(blank=True, null=True)),
                ('send_day', models.SmallIntegerField(
                    blank=True,
                    help_text='0–6 for weekly (Sun=0), 1–28 for monthly',
                    null=True,
                )),
                ('starts_at', models.DateField(blank=True, null=True)),
                ('ends_at', models.DateField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[('draft', 'Draft'), ('scheduled', 'Scheduled'), ('sent', 'Sent'), ('failed', 'Failed'), ('cancelled', 'Cancelled')],
                    default='draft',
                    max_length=12,
                )),
                ('next_run_at', models.DateTimeField(blank=True, null=True)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('school', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='scheduled_messages',
                    to='classroom.school',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='scheduled_messages',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='scheduledmessage',
            index=models.Index(fields=['school', 'status'], name='classroom_s_school__idx'),
        ),
        migrations.AddIndex(
            model_name='scheduledmessage',
            index=models.Index(fields=['next_run_at'], name='classroom_s_next_ru_idx'),
        ),
    ]
