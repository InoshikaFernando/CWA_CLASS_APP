from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brainbuzz', '0008_sessionquestion_time_limit_sec'),
    ]

    operations = [
        migrations.AddField(
            model_name='brainbuzzsessionquestion',
            name='image_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Absolute URL of the question image, snapshotted at session creation.',
                max_length=2048,
            ),
        ),
        migrations.AlterField(
            model_name='brainbuzzsessionquestion',
            name='options_json',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='MCQ/TF options: [{"label":"A","text":"...","is_correct":true,"image_url":""}]',
            ),
        ),
    ]
