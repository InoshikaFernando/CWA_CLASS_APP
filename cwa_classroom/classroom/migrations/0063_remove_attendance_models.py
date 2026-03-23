"""
Remove ClassSession, StudentAttendance, TeacherAttendance from classroom
app state and re-point ProgressRecord.session to attendance.ClassSession.

The actual database tables are preserved (now managed by the attendance app
via db_table settings).  No schema changes occur.

Part of CPP-64 — decoupling the attendance module.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0062_add_school_company_fields'),
        # attendance.0001 must run first so attendance.ClassSession exists in state
        ('attendance', '0001_initial'),
    ]

    operations = [
        # 1. Re-point ProgressRecord.session FK from classroom.ClassSession
        #    to attendance.ClassSession (state-only, DB column unchanged)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='progressrecord',
                    name='session',
                    field=models.ForeignKey(
                        blank=True,
                        help_text='Optional: the session during which this progress was recorded.',
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='progress_records',
                        to='attendance.classsession',
                    ),
                ),
            ],
            database_operations=[],
        ),
        # 2. Remove attendance models from classroom state
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='StudentAttendance'),
                migrations.DeleteModel(name='TeacherAttendance'),
                migrations.DeleteModel(name='ClassSession'),
            ],
            database_operations=[],
        ),
    ]
