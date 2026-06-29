# CPP-316: Stage progression tracking — LanguageProgress model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0006_cpp314_crossword_puzzle_data'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LanguageProgress',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('exercises_completed', models.PositiveIntegerField(default=0)),
                ('exercises_total', models.PositiveIntegerField(default=0)),
                ('best_score_avg', models.FloatField(default=0.0)),
                ('is_unlocked', models.BooleanField(default=False)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('student', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='language_progress',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('topic_level', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='student_progress',
                    to='languages.languagetopiclevel',
                )),
            ],
            options={
                'unique_together': {('student', 'topic_level')},
            },
        ),
    ]
