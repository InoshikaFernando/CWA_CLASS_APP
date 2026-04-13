from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_pending_registration'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='creation_method',
            field=models.CharField(
                blank=True,
                choices=[('institute', 'Institute Created'), ('self_registered', 'Self Registered')],
                default='self_registered',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='customuser',
            name='welcome_email_sent',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Timestamp of when the welcome email was sent. Null = not yet sent.',
            ),
        ),
    ]
