from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0096_perf_composite_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='invoice_recipient_policy',
            field=models.CharField(
                choices=[
                    ('parents_fallback_student', 'Parents (student if no parents)'),
                    ('parents_only', 'Parents only (no email if no parents)'),
                    ('parents_and_student', 'Parents and student always'),
                    ('student_only', 'Student only'),
                ],
                default='parents_fallback_student',
                help_text='Controls who receives invoice and cancellation emails.',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='department',
            name='invoice_recipient_policy',
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
