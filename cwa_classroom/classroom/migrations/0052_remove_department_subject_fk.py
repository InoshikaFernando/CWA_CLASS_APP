# Step 3: Remove old Department.subject FK (data already migrated to DepartmentSubject)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0051_migrate_department_subjects_data'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='department',
            name='subject',
        ),
    ]
