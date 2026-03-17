"""
Backfill DepartmentLevel rows for existing departments that were created
before the DepartmentLevel M2M feature was added.

For each department, iterates its DepartmentSubject links and auto-maps
global levels for each subject. Basic Facts (100-199) are always excluded.

Usage:
    python manage.py backfill_department_levels
    python manage.py backfill_department_levels --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from classroom.models import Department, DepartmentLevel, DepartmentSubject, Level


class Command(BaseCommand):
    help = 'Backfill DepartmentLevel M2M rows for existing departments.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be created without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total_created = 0

        dept_subjects = (
            DepartmentSubject.objects.filter(department__is_active=True)
            .select_related('department', 'department__school', 'subject')
            .order_by('department__school__name', 'department__name')
        )

        for ds in dept_subjects:
            dept = ds.department
            subject_levels = Level.objects.filter(
                subject=ds.subject, school__isnull=True,
            ).exclude(
                level_number__gte=100, level_number__lt=200,
            ).order_by('level_number')

            created_count = 0
            for lv in subject_levels:
                if dry_run:
                    exists = DepartmentLevel.objects.filter(
                        department=dept, level=lv,
                    ).exists()
                    if not exists:
                        created_count += 1
                else:
                    _, created = DepartmentLevel.objects.get_or_create(
                        department=dept, level=lv,
                        defaults={'order': lv.level_number},
                    )
                    if created:
                        created_count += 1

            if created_count:
                total_created += created_count
                self.stdout.write(
                    f'  {dept.school.name} / {dept.name} / {ds.subject.name}: '
                    f'{created_count} levels {"would be " if dry_run else ""}mapped'
                )

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done. {total_created} DepartmentLevel rows {"would be " if dry_run else ""}created.'
        ))
