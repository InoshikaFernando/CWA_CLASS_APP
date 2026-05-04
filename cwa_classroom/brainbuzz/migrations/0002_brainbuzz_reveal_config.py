from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brainbuzz', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='brainbuzzsession',
            name='config_json',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Session creation params stored for the "repeat session" feature.',
            ),
        ),
        migrations.AlterField(
            model_name='brainbuzzsession',
            name='status',
            field=models.CharField(
                choices=[
                    ('lobby', 'Lobby'),
                    ('active', 'Active'),
                    ('reveal', 'Reveal'),
                    ('between', 'Between Questions'),
                    ('finished', 'Finished'),
                    ('cancelled', 'Cancelled'),
                ],
                db_index=True,
                default='lobby',
                max_length=20,
            ),
        ),
    ]
