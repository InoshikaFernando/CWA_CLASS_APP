# Generated for CPP-312: phonics MCQ audio file fallback

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0004_cpp311_score_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='languageexercise',
            name='audio_file',
            field=models.FileField(blank=True, upload_to='languages/audio/'),
        ),
    ]
