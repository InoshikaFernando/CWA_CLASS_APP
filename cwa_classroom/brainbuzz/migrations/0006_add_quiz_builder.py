"""
Migration: add BrainBuzzQuiz, BrainBuzzQuizQuestion, BrainBuzzQuizOption models.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brainbuzz', '0005_seed_questions'),
        ('classroom', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BrainBuzzQuiz',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('is_draft', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('subject', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='brainbuzz_quizzes',
                    to='classroom.subject',
                )),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='brainbuzz_quizzes',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddIndex(
            model_name='brainbuzzquiz',
            index=models.Index(fields=['created_by', 'is_draft'], name='bb_quiz_creator_draft_idx'),
        ),
        migrations.CreateModel(
            name='BrainBuzzQuizQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_text', models.TextField()),
                ('question_type', models.CharField(
                    choices=[
                        ('mcq', 'Multiple Choice'),
                        ('tf', 'True / False'),
                        ('short', 'Short Answer'),
                        ('fill_blank', 'Fill in the Blank'),
                    ],
                    default='mcq',
                    max_length=20,
                )),
                ('time_limit', models.IntegerField(
                    default=20,
                    help_text='Seconds allocated for this question when played live.',
                )),
                ('order', models.IntegerField(default=0)),
                ('correct_short_answer', models.TextField(
                    blank=True,
                    null=True,
                    help_text='Correct answer text for short-answer / fill-blank types.',
                )),
                ('quiz', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='quiz_questions',
                    to='brainbuzz.brainbuzzquiz',
                )),
            ],
            options={
                'ordering': ['quiz', 'order'],
            },
        ),
        migrations.AddIndex(
            model_name='brainbuzzquizquestion',
            index=models.Index(fields=['quiz', 'order'], name='bb_qq_quiz_order_idx'),
        ),
        migrations.CreateModel(
            name='BrainBuzzQuizOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('option_text', models.CharField(max_length=500)),
                ('is_correct', models.BooleanField(default=False)),
                ('order', models.IntegerField(default=0)),
                ('question', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='quiz_options',
                    to='brainbuzz.brainbuzzquizquestion',
                )),
            ],
            options={
                'ordering': ['question', 'order'],
            },
        ),
        migrations.AddIndex(
            model_name='brainbuzzquizoption',
            index=models.Index(fields=['question', 'order'], name='bb_qo_question_order_idx'),
        ),
    ]
