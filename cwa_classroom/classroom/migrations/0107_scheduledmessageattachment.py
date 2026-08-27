from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0106_rename_classroom_s_school__idx_classroom_s_school__f782a3_idx_and_more'),
        ('classroom', '0105_school_subscription_discount_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduledMessageAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='messaging/attachments/%Y/%m/')),
                ('filename', models.CharField(max_length=255)),
                ('filesize', models.PositiveIntegerField(default=0, help_text='Bytes')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('message', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attachments',
                    to='classroom.scheduledmessage',
                )),
            ],
        ),
    ]
