from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0023_alter_homework_options_alter_homework_managers'),
    ]

    operations = [
        migrations.AlterField(
            model_name='homework',
            name='homework_type',
            field=models.CharField(
                choices=[
                    ('topic', 'Topic Quiz'),
                    ('mixed', 'Mixed Quiz'),
                    ('pdf_upload', 'PDF Upload'),
                    ('json_upload', 'JSON Upload'),
                ],
                default='topic',
                max_length=20,
            ),
        ),
    ]
