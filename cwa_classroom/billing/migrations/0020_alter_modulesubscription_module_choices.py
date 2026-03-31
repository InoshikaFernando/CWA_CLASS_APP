from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0019_seed_ai_import_modules'),
    ]

    operations = [
        migrations.AlterField(
            model_name='modulesubscription',
            name='module',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('teachers_attendance', 'Teachers Attendance'),
                    ('students_attendance', 'Students Attendance'),
                    ('student_progress_reports', 'Student Progress Reports'),
                    ('ai_import_starter', 'AI Question Import - Starter'),
                    ('ai_import_professional', 'AI Question Import - Professional'),
                    ('ai_import_enterprise', 'AI Question Import - Enterprise'),
                ],
            ),
        ),
    ]
