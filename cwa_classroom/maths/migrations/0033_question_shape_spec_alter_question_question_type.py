from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('maths', '0032_seed_geometry_questions'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='shape_spec',
            field=models.JSONField(blank=True, help_text='shape_select only. Scene of shapes + the target type to find (set-comparison graded).', null=True),
        ),
        migrations.AlterField(
            model_name='question',
            name='question_type',
            field=models.CharField(choices=[('multiple_choice', 'Multiple Choice'), ('true_false', 'True/False'), ('short_answer', 'Short Answer'), ('fill_blank', 'Fill in the Blank'), ('calculation', 'Calculation'), ('extended_answer', 'Extended Answer (written proof/explanation)'), ('long_division', 'Long Division'), ('prime_factorization', 'Prime Factorization'), ('column_operation', 'Column Arithmetic'), ('measure', 'Measure (angle/scale, tolerance-graded)'), ('draw_on_grid', 'Draw on Grid (symmetry / reflection / plot)'), ('shape_select', 'Shape Select (find & colour shapes)')], default='multiple_choice', max_length=20),
        ),
    ]
