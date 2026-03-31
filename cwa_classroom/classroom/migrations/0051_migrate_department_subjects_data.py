# Step 2: Data migration — copy Department.subject FK → DepartmentSubject rows

from django.db import migrations


def forward(apps, schema_editor):
    """Copy each Department's old subject FK into the new DepartmentSubject M2M."""
    db_alias = schema_editor.connection.alias
    # Use raw SQL to avoid model-state issues when running from scratch
    with schema_editor.connection.cursor() as cursor:
        # Check if subject_id column exists (may not on fresh test DBs with squashed migrations)
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'classroom_department' "
            "AND column_name = 'subject_id'"
        )
        if cursor.fetchone()[0] == 0:
            return  # Column doesn't exist, nothing to migrate

        cursor.execute(
            "INSERT IGNORE INTO classroom_departmentsubject (department_id, subject_id, `order`, created_at) "
            "SELECT id, subject_id, 0, NOW() FROM classroom_department WHERE subject_id IS NOT NULL"
        )


def reverse(apps, schema_editor):
    """Reverse: copy first DepartmentSubject back to Department.subject FK."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'classroom_department' "
            "AND column_name = 'subject_id'"
        )
        if cursor.fetchone()[0] == 0:
            return

        cursor.execute(
            "UPDATE classroom_department d "
            "INNER JOIN ("
            "  SELECT department_id, subject_id FROM classroom_departmentsubject "
            "  ORDER BY `order` LIMIT 1"
            ") ds ON d.id = ds.department_id "
            "SET d.subject_id = ds.subject_id "
            "WHERE d.subject_id IS NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0050_department_subjects_m2m'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
