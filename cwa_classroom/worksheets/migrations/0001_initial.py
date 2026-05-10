from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('classroom', '0086_parentstudent_school_nullable'),
        ('maths', '0017_cleanup_orphaned_questions'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Worksheet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('original_filename', models.CharField(max_length=255)),
                ('pdf_file', models.FileField(blank=True, null=True, upload_to='worksheets/pdfs/')),
                ('question_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheets', to='classroom.school')),
                ('level', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='worksheets', to='classroom.level')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_worksheets', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='WorksheetQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField()),
                ('worksheet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheet_questions', to='worksheets.worksheet')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheet_entries', to='maths.question')),
            ],
            options={'ordering': ['order']},
        ),
        migrations.AddConstraint(
            model_name='worksheetquestion',
            constraint=models.UniqueConstraint(fields=('worksheet', 'order'), name='unique_worksheet_question_order'),
        ),
        migrations.CreateModel(
            name='WorksheetUploadSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('pdf_filename', models.CharField(max_length=255)),
                ('worksheet_name', models.CharField(blank=True, max_length=255)),
                ('extracted_data', models.JSONField(default=dict)),
                ('extracted_images', models.JSONField(default=dict)),
                ('page_count', models.PositiveIntegerField(default=0)),
                ('tokens_used', models.PositiveIntegerField(default=0)),
                ('is_confirmed', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheet_upload_sessions', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='classroom.school')),
                ('worksheet', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='upload_sessions', to='worksheets.worksheet')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='WorksheetAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_start', models.PositiveIntegerField(default=1, help_text='First question order number (1-based)')),
                ('question_end', models.PositiveIntegerField(blank=True, help_text='Last question order number inclusive (null = all)', null=True)),
                ('assigned_at', models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
                ('worksheet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='worksheets.worksheet')),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheet_assignments', to='classroom.classroom')),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='worksheet_assignments', to='classroom.classsession')),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_worksheet_assignments', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-assigned_at']},
        ),
        migrations.CreateModel(
            name='WorksheetSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('score', models.PositiveIntegerField(default=0)),
                ('total_questions', models.PositiveIntegerField(default=0)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='worksheets.worksheetassignment')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheet_submissions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-started_at'], 'unique_together': {('assignment', 'student')}},
        ),
        migrations.CreateModel(
            name='WorksheetStudentAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text_answer', models.TextField(blank=True)),
                ('is_correct', models.BooleanField(default=False)),
                ('points_earned', models.FloatField(default=0.0)),
                ('answered_at', models.DateTimeField(auto_now_add=True)),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='worksheets.worksheetsubmission')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='worksheet_student_answers', to='maths.question')),
                ('selected_answer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='worksheet_student_answers', to='maths.answer')),
            ],
            options={'unique_together': {('submission', 'question')}},
        ),
    ]
