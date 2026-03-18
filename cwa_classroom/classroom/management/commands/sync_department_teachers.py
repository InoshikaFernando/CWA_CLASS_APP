"""
One-time management command to sync existing ClassTeacher assignments
to DepartmentTeacher entries.

Run with:  python manage.py sync_department_teachers
"""
from django.core.management.base import BaseCommand

from classroom.models import ClassTeacher, DepartmentTeacher


class Command(BaseCommand):
    help = 'Ensure every teacher assigned to a class is also in that department'

    def handle(self, *args, **options):
        created_count = 0
        skipped_count = 0

        class_teachers = ClassTeacher.objects.select_related(
            'classroom', 'teacher',
        ).filter(classroom__department__isnull=False)

        for ct in class_teachers:
            _, created = DepartmentTeacher.objects.get_or_create(
                department_id=ct.classroom.department_id,
                teacher=ct.teacher,
            )
            if created:
                created_count += 1
                self.stdout.write(
                    f'  + {ct.teacher.username} → {ct.classroom.department}'
                )
            else:
                skipped_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {created_count} new department memberships created, '
            f'{skipped_count} already existed.'
        ))
