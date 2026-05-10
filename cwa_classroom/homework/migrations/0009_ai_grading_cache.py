"""Add AIGradingCache model for fuzzy-matched answer caching."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('homework', '0008_pdf_upload_and_review'),
        ('maths', '0018_extended_answer_and_grading'),
    ]

    operations = [
        migrations.CreateModel(
            name='AIGradingCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('normalised_answer', models.CharField(
                    max_length=500,
                    help_text='Lowercased, whitespace-collapsed answer text (first 500 chars) used for matching.',
                )),
                ('is_correct', models.BooleanField()),
                ('score_fraction', models.FloatField(
                    help_text='Claude score 0.0–1.0.',
                )),
                ('feedback', models.TextField(
                    help_text='Feedback returned by Claude for this answer pattern.',
                )),
                ('hit_count', models.PositiveIntegerField(
                    default=0,
                    help_text='How many subsequent student answers matched this cache entry.',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('question', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='grading_cache_entries',
                    to='maths.question',
                )),
            ],
            options={
                'ordering': ['-hit_count', '-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='aigradingcache',
            constraint=models.UniqueConstraint(
                fields=['question', 'normalised_answer'],
                name='unique_grading_cache_entry',
            ),
        ),
        migrations.AddIndex(
            model_name='aigradingcache',
            index=models.Index(fields=['question'], name='grading_cache_question_idx'),
        ),
    ]
