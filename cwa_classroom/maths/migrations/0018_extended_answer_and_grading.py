"""Add extended_answer question type, validation_type, and grading_rubric to Question."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0017_cleanup_orphaned_questions'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='validation_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('auto', 'Auto (system checks exact answer)'),
                    ('ai_graded', 'AI Graded (Claude evaluates reasoning)'),
                    ('human_graded', 'Human Graded (teacher reviews manually)'),
                ],
                default='auto',
                help_text='How student answers are validated. Extended answers use ai_graded or human_graded.',
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='grading_rubric',
            field=models.TextField(
                blank=True,
                help_text=(
                    'Marking guide for AI or teacher graders. '
                    'For extended_answer questions: describe what a correct answer must include, '
                    'common mistakes to look for, and partial-credit criteria.'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='question',
            name='question_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('multiple_choice', 'Multiple Choice'),
                    ('true_false', 'True/False'),
                    ('short_answer', 'Short Answer'),
                    ('fill_blank', 'Fill in the Blank'),
                    ('calculation', 'Calculation'),
                    ('extended_answer', 'Extended Answer (written proof/explanation)'),
                ],
                default='multiple_choice',
            ),
        ),
    ]
