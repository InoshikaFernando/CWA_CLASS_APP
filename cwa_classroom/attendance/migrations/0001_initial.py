"""
attendance/migrations/0001_initial.py
State-only migration for CPP-64.
db_table preserved on all models — no ALTER TABLE, no data movement.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('classroom', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='ClassSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('status', models.CharField(choices=[('scheduled','Scheduled'),('completed','Completed'),('cancelled','Cancelled')], default='scheduled', max_length=20)),
                ('cancellation_reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='classroom.classroom')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['date', 'start_time'], 'db_table': 'classroom_classsession'},
        ),
        migrations.CreateModel(
            name='StudentAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('present','Present'),('absent','Absent'),('late','Late')], default='present', max_length=10)),
                ('marked_at', models.DateTimeField(auto_now_add=True)),
                ('self_reported', models.BooleanField(default=False)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_attendance', to='attendance.classsession')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_records', to=settings.AUTH_USER_MODEL)),
                ('marked_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_marks_given', to=settings.AUTH_USER_MODEL)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_attendance_approvals', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['session', 'student'], 'db_table': 'classroom_studentattendance'},
        ),
        migrations.AddConstraint(model_name='studentattendance', constraint=models.UniqueConstraint(fields=['session', 'student'], name='unique_student_session_attendance')),
        migrations.CreateModel(
            name='TeacherAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('present','Present'),('absent','Absent'),('late','Late')], default='present', max_length=10)),
                ('self_reported', models.BooleanField(default=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teacher_attendance', to='attendance.classsession')),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teacher_attendance_records', to=settings.AUTH_USER_MODEL)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='teacher_attendance_approvals', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'classroom_teacheratttendance'},
        ),
        migrations.AddConstraint(model_name='teacheratttendance', constraint=models.UniqueConstraint(fields=['session', 'teacher'], name='unique_teacher_session_attendance')),
    ]
