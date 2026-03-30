"""
Management command to wipe all imported data for a school, leaving
global data (Levels, Subjects, Topics, Roles) intact.

Useful for re-running CSV imports without data conflicts.

Usage:
    python manage.py clean_school                    # dry-run — shows counts
    python manage.py clean_school --confirm          # actually delete
    python manage.py clean_school --school 3         # target school by id
    python manage.py clean_school --school 3 --confirm
    python manage.py clean_school --keep-users       # delete school data but not user accounts
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        'Wipe all imported data for a school (students, teachers, classes, '
        'departments, guardians) while keeping global levels/subjects/topics.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--school',
            type=int,
            default=None,
            help='School ID to clean. If omitted and only one school exists, uses that one.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually delete. Without this flag the command only shows a dry-run.',
        )
        parser.add_argument(
            '--keep-users',
            action='store_true',
            help='Delete school-data records but keep the underlying user accounts.',
        )

    def handle(self, *args, **options):
        from classroom.models import (
            School, Department, ClassRoom, ClassTeacher, ClassStudent,
            SchoolTeacher, SchoolStudent, Guardian, DepartmentSubject,
            DepartmentTeacher, Level, ClassSession,
        )
        from accounts.models import CustomUser, UserRole

        confirm = options['confirm']
        keep_users = options['keep_users']

        # --- Resolve school ---
        school_id = options['school']
        if school_id:
            try:
                school = School.objects.get(pk=school_id)
            except School.DoesNotExist:
                raise CommandError(f'School with id={school_id} does not exist.')
        else:
            schools = list(School.objects.all())
            if len(schools) == 0:
                raise CommandError('No schools found in the database.')
            if len(schools) > 1:
                ids = ', '.join(f'{s.id}: {s.name}' for s in schools)
                raise CommandError(
                    f'Multiple schools found — specify one with --school <id>.\n  {ids}'
                )
            school = schools[0]

        self.stdout.write(self.style.WARNING(f'\n=== Clean School: {school.name} (id={school.id}) ==='))

        # --- Gather counts ---
        student_users = CustomUser.objects.filter(
            school_student_entries__school=school,
        ).distinct()
        teacher_users = CustomUser.objects.filter(
            school_memberships__school=school,
        ).distinct()

        counts = {
            'ClassSession':      ClassSession.objects.filter(classroom__school=school).count(),
            'ClassStudent':      ClassStudent.objects.filter(classroom__school=school).count(),
            'ClassTeacher':      ClassTeacher.objects.filter(classroom__school=school).count(),
            'ClassRoom':         ClassRoom.objects.filter(school=school).count(),
            'Guardian':          Guardian.objects.filter(school=school).count(),
            'SchoolStudent':     SchoolStudent.objects.filter(school=school).count(),
            'SchoolTeacher':     SchoolTeacher.objects.filter(school=school).count(),
            'DepartmentSubject': DepartmentSubject.objects.filter(department__school=school).count(),
            'Department':        Department.objects.filter(school=school).count(),
        }
        if not keep_users:
            counts['student users'] = student_users.count()
            counts['teacher users'] = teacher_users.count()

        for label, count in counts.items():
            self.stdout.write(f'  {label:<22} {count}')

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                '\nDry-run — nothing deleted. Run with --confirm to delete.'
            ))
            return

        # --- Delete ---
        with transaction.atomic():
            ClassSession.objects.filter(classroom__school=school).delete()
            ClassStudent.objects.filter(classroom__school=school).delete()
            ClassTeacher.objects.filter(classroom__school=school).delete()
            ClassRoom.objects.filter(school=school).delete()
            Guardian.objects.filter(school=school).delete()
            SchoolStudent.objects.filter(school=school).delete()

            if not keep_users:
                # Delete student/teacher user accounts (cascades UserRole etc.)
                student_users.delete()
                teacher_users.delete()

            SchoolTeacher.objects.filter(school=school).delete()
            DepartmentSubject.objects.filter(department__school=school).delete()
            Department.objects.filter(school=school).delete()

        self.stdout.write(self.style.SUCCESS(
            f'\nSchool "{school.name}" cleaned successfully.'
        ))
