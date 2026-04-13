"""
Migration: update CodingLanguage.slug choices

Replaces the combined 'html-css' choice with separate 'html' and 'css' choices
so that HTML and CSS are distinct language records as required by the platform spec.

Note: Django choices are not enforced at the database level for SlugField, so this
migration contains no SQL — it only updates the migration state.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='codinglanguage',
            name='slug',
            field=models.SlugField(
                unique=True,
                choices=[
                    ('python', 'Python'),
                    ('javascript', 'JavaScript'),
                    ('html', 'HTML'),
                    ('css', 'CSS'),
                    ('scratch', 'Scratch'),
                ],
            ),
        ),
    ]
