# CPP-316: Add language_topic_levels M2M to Homework

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0023_alter_homework_options_alter_homework_managers'),
        ('languages', '0007_cpp316_language_progress'),
    ]

    operations = [
        migrations.AddField(
            model_name='homework',
            name='language_topic_levels',
            field=models.ManyToManyField(
                blank=True,
                related_name='homeworks',
                to='languages.languagetopiclevel',
            ),
        ),
    ]
