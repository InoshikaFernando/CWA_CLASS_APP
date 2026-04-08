"""
Management command to wipe all imported data for a school, leaving
global data (Levels, Subjects, Topics, Roles) intact.

Useful for re-running CSV imports without data conflicts.

Usage:
    python manage.py clean_school                         # dry-run — shows counts
    python manage.py clean_school --confirm               # wipe data, keep School record
    python manage.py clean_school --delete --confirm      # cascade delete the whole School record
    python manage.py clean_school --school 3 --confirm    # target school by id
    python manage.py clean_school --name sipsewana --delete --confirm  # target by name
    python manage.py clean_school --keep-users            # delete school data but not user accounts
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        'Wipe all imported data for a school (students, teachers, classes, '
        'departments, guardians). Use --delete to also remove the School record itself.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--school',
            type=int,
            default=None,
            help='School ID to clean. If omitted and only one school exists, uses that one.',
        )
        parser.add_argument(
            '--name',
            default=None,
            help='School name (or partial match) to clean.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually delete. Without this flag the command only shows a dry-run.',
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Cascade delete the School record itself (not just its data).',
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
            Level, ClassSession,
        )
        from accounts.models import CustomUser

        confirm = options['confirm']
        keep_users = options['keep_users']
        delete_school = options['delete']

        # --- Resolve school ---
        school_id = options['school']
        name_query = options['name']

        if school_id:
            try:
                school = School.objects.get(pk=school_id)
            except School.DoesNotExist:
                raise CommandError(f'School with id={school_id} does not exist.')
        elif name_query:
            matches = list(School.objects.filter(name__icontains=name_query))
            if not matches:
                all_schools = ', '.join(f'{s.id}: {s.name}' for s in School.objects.all())
                raise CommandError(
                    f'No school matching "{name_query}".\n  Available: {all_schools}'
                )
            if len(matches) > 1:
                ids = ', '.join(f'{s.id}: {s.name}' for s in matches)
                raise CommandError(
                    f'Multiple schools match "{name_query}" — use --school <id>.\n  {ids}'
                )
            school = matches[0]
        else:
            schools = list(School.objects.all())
            if len(schools) == 0:
                raise CommandError('No schools found in the database.')
            if len(schools) > 1:
                ids = ', '.join(f'{s.id}: {s.name}' for s in schools)
                raise CommandError(
                    f'Multiple schools found — specify one with --school <id> or --name.\n  {ids}'
                )
            school = schools[0]

        action = 'DELETE school record + all data' if delete_school else 'Clean school data'
        self.stdout.write(self.style.WARNING(
            f'\n=== {action}: {school.name} (id={school.id}) ==='
        ))

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
        if delete_school:
            counts['School record'] = 1
            if not keep_users and school.admin:
                counts['admin (HoI) user'] = f'1  ({school.admin.username} / {school.admin.email})'

        for label, count in counts.items():
            self.stdout.write(f'  {label:<22} {count}')

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                '\nDry-run — nothing deleted. Run with --confirm to delete.'
            ))
            return

        # --- Delete ---
        with transaction.atomic():
            if delete_school:
                # School.admin uses SET_NULL so we must delete the admin user separately.
                admin_user = school.admin
                # Django CASCADE handles students/teachers/classes/departments.
                school.delete()
                if admin_user and not keep_users:
                    admin_user.delete()
                    self.stdout.write(f'  Deleted admin user: {admin_user.username} ({admin_user.email})')
                self.stdout.write(self.style.SUCCESS(
                    f'\nSchool "{school.name}" and all related data deleted (cascade).'
                ))
            else:
                # Manual ordered deletion (keeps the School record).
                ClassSession.objects.filter(classroom__school=school).delete()
                ClassStudent.objects.filter(classroom__school=school).delete()
                ClassTeacher.objects.filter(classroom__school=school).delete()
                ClassRoom.objects.filter(school=school).delete()
                Guardian.objects.filter(school=school).delete()
                SchoolStudent.objects.filter(school=school).delete()

                if not keep_users:
                    CustomUser.objects.filter(pk__in=list(student_users.values_list('pk', flat=True))).delete()
                    CustomUser.objects.filter(pk__in=list(teacher_users.values_list('pk', flat=True))).delete()

                SchoolTeacher.objects.filter(school=school).delete()
                DepartmentSubject.objects.filter(department__school=school).delete()
                Department.objects.filter(school=school).delete()

                self.stdout.write(self.style.SUCCESS(
                    f'\nSchool "{school.name}" data cleaned. School record kept.'
                ))
