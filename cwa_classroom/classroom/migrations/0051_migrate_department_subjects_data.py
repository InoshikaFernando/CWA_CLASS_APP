# Step 2: Data migration — copy Department.subject FK → DepartmentSubject rows

from django.db import migrations


def forward(apps, schema_editor):
    """Copy each Department's old subject FK into the new DepartmentSubject M2M."""
    Department = apps.get_model('classroom', 'Department')
    DepartmentSubject = apps.get_model('classroom', 'DepartmentSubject')
    for dept in Department.objects.filter(subject__isnull=False):
        DepartmentSubject.objects.get_or_create(
            department=dept,
            subject=dept.subject,
            defaults={'order': 0},
        )


def reverse(apps, schema_editor):
    """Reverse: copy first DepartmentSubject back to Department.subject FK."""
    Department = apps.get_model('classroom', 'Department')
    DepartmentSubject = apps.get_model('classroom', 'DepartmentSubject')
    for ds in DepartmentSubject.objects.select_related('department', 'subject').order_by('order'):
        dept = ds.department
        if dept.subject is None:
            dept.subject = ds.subject
            dept.save(update_fields=['subject'])


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0050_department_subjects_m2m'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
