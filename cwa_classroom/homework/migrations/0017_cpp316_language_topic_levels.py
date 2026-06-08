# CPP-316: Add language_topic_levels M2M to Homework

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0016_merge_20260520_1011'),
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
