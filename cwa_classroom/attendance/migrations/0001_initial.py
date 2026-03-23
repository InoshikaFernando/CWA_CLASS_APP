"""
attendance/migrations/0001_initial.py
State-only migration for CPP-64.
Registers ClassSession, StudentAttendance, TeacherAttendance in the
attendance app's model state.  The underlying database tables already
exist (created by classroom migration 0033) and are preserved via
explicit db_table settings — no schema changes occur.

On a fresh database (including test DBs), the tables are created by
classroom.0033; this migration only updates Django's state tracking.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('classroom', '0061_merge_0060_parent_models_0060_school_suspension'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='ClassSession',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('date', models.DateField()),
                        ('start_time', models.TimeField()),
                        ('end_time', models.TimeField()),
                        ('status', models.CharField(choices=[('scheduled', 'Scheduled'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='scheduled', max_length=20)),
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
                        ('status', models.CharField(choices=[('present', 'Present'), ('absent', 'Absent'), ('late', 'Late')], default='present', max_length=10)),
                        ('marked_at', models.DateTimeField(auto_now_add=True)),
                        ('self_reported', models.BooleanField(default=False)),
                        ('approved_at', models.DateTimeField(blank=True, null=True)),
                        ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_attendance', to='attendance.classsession')),
                        ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_records', to=settings.AUTH_USER_MODEL)),
                        ('marked_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_marks_given', to=settings.AUTH_USER_MODEL)),
                        ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_attendance_approvals', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={'ordering': ['session', 'student'], 'unique_together': {('session', 'student')}, 'db_table': 'classroom_studentattendance'},
                ),
                migrations.CreateModel(
                    name='TeacherAttendance',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('status', models.CharField(choices=[('present', 'Present'), ('absent', 'Absent'), ('late', 'Late')], default='present', max_length=10)),
                        ('self_reported', models.BooleanField(default=True)),
                        ('approved_at', models.DateTimeField(blank=True, null=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teacher_attendance', to='attendance.classsession')),
                        ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teacher_attendance_records', to=settings.AUTH_USER_MODEL)),
                        ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='teacher_attendance_approvals', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={'unique_together': {('session', 'teacher')}, 'db_table': 'classroom_teacherattendance'},
                ),
            ],
            database_operations=[],
        ),
    ]
