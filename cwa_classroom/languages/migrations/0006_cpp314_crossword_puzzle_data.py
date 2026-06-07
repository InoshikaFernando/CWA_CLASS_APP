# Generated for CPP-314: crossword puzzle data field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0005_cpp312_audio_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='languageexercise',
            name='puzzle_data',
            field=models.JSONField(default=dict, blank=True),
        ),
    ]
