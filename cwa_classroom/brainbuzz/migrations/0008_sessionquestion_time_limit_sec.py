from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brainbuzz', '0007_participant_avatar'),
    ]

    operations = [
        migrations.AddField(
            model_name='brainbuzzsessionquestion',
            name='time_limit_sec',
            field=models.IntegerField(default=20),
        ),
    ]
