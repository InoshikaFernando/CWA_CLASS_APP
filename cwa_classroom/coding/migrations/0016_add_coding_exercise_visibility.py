# Generated migration for adding visibility fields to CodingExercise
# Adds school, department, classroom ForeignKeys to support role-based question visibility

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0001_initial'),  # Adjust if needed based on classroom migration order
        ('coding', '0015_alter_codingexercise_question_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='codingexercise',
            name='school',
            field=models.ForeignKey(
                blank=True,
                help_text='Null = global/shared exercise. Set = private to this school only.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='coding_exercises',
                to='classroom.school',
            ),
        ),
        migrations.AddField(
            model_name='codingexercise',
            name='department',
            field=models.ForeignKey(
                blank=True,
                help_text='Null = not department-scoped. Set = visible to this department only.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='coding_exercises',
                to='classroom.department',
            ),
        ),
        migrations.AddField(
            model_name='codingexercise',
            name='classroom',
            field=models.ForeignKey(
                blank=True,
                help_text='Null = not class-scoped. Set = visible to this class only.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='coding_exercises',
                to='classroom.classroom',
            ),
        ),
    ]
