"""
Management command to delete all imported data (students, teachers, parents,
classes, departments) for a given school — or ALL schools.

Intended for test environments only.

Usage:
    python manage.py clear_import_data                     # dry-run, all schools
    python manage.py clear_import_data --school "Sipsetha"  # dry-run, one school
    python manage.py clear_import_data --confirm            # actually delete all
    python manage.py clear_import_data --school "Sipsetha" --confirm
    python manage.py clear_import_data --nuke --confirm     # delete schools too + orphan users
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import CustomUser, UserRole
from classroom.models import (
    School, SchoolStudent, SchoolTeacher, Guardian, StudentGuardian,
    ClassRoom, ClassStudent, ClassTeacher, Department, DepartmentTeacher,
    ClassSession, StudentAttendance, TeacherAttendance,
)


class Command(BaseCommand):
    help = 'Delete imported students, teachers, parents, classes for a school (test env).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--school', type=str, default=None,
            help='School name (partial match). Omit to target all schools.',
        )
        parser.add_argument(
            '--confirm', action='store_true',
            help='Actually delete. Without this flag, only a dry-run summary is shown.',
        )
        parser.add_argument(
            '--nuke', action='store_true',
            help='Also delete the School record(s) themselves and orphaned users.',
        )

    def handle(self, *args, **options):
        school_filter = options['school']
        confirm = options['confirm']
        nuke = options['nuke']

        # --- Resolve schools ---
        if school_filter:
            schools = School.objects.filter(name__icontains=school_filter)
        else:
            schools = School.objects.all()

        if not schools.exists():
            self.stdout.write(self.style.WARNING('No schools found.'))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{"DELETE" if confirm else "DRY-RUN"} — targeting {schools.count()} school(s):'
        ))
        for s in schools:
            self.stdout.write(f'  • {s.name} (id={s.pk})')

        # --- Gather counts ---
        school_ids = list(schools.values_list('pk', flat=True))

        student_memberships = SchoolStudent.objects.filter(school_id__in=school_ids)
        teacher_memberships = SchoolTeacher.objects.filter(school_id__in=school_ids)
        guardians = Guardian.objects.filter(school_id__in=school_ids)
        student_guardian_links = StudentGuardian.objects.filter(
            guardian__school_id__in=school_ids,
        )
        classrooms = ClassRoom.objects.filter(department__school_id__in=school_ids)
        class_students = ClassStudent.objects.filter(classroom__department__school_id__in=school_ids)
        class_teachers = ClassTeacher.objects.filter(classroom__department__school_id__in=school_ids)
        departments = Department.objects.filter(school_id__in=school_ids)
        dept_teachers = DepartmentTeacher.objects.filter(department__school_id__in=school_ids)
        sessions = ClassSession.objects.filter(classroom__department__school_id__in=school_ids)

        # Collect user IDs that will become orphaned
        student_user_ids = set(student_memberships.values_list('student_id', flat=True))
        teacher_user_ids = set(teacher_memberships.values_list('teacher_id', flat=True))

        counts = {
            'SchoolStudent': student_memberships.count(),
            'SchoolTeacher': teacher_memberships.count(),
            'Guardian': guardians.count(),
            'StudentGuardian': student_guardian_links.count(),
            'ClassStudent': class_students.count(),
            'ClassTeacher': class_teachers.count(),
            'ClassRoom': classrooms.count(),
            'ClassSession': sessions.count(),
            'Department': departments.count(),
            'DepartmentTeacher': dept_teachers.count(),
            'Student users': len(student_user_ids),
            'Teacher users': len(teacher_user_ids),
        }

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Records to delete:'))
        for label, count in counts.items():
            style = self.style.WARNING if count > 0 else self.style.SUCCESS
            self.stdout.write(f'  {label:25s} {style(str(count))}')

        if nuke:
            self.stdout.write(f'  {"School":25s} {self.style.ERROR(str(schools.count()))}')

        if not confirm:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                'Dry-run complete. Add --confirm to actually delete.'
            ))
            return

        # --- Delete ---
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Deleting...'))

        with transaction.atomic():
            # Delete link tables first
            n, _ = student_guardian_links.delete()
            self.stdout.write(f'  Deleted StudentGuardian: {n}')

            n, _ = class_students.delete()
            self.stdout.write(f'  Deleted ClassStudent: {n}')

            n, _ = class_teachers.delete()
            self.stdout.write(f'  Deleted ClassTeacher: {n}')

            n, _ = sessions.delete()
            self.stdout.write(f'  Deleted ClassSession: {n}')

            n, _ = dept_teachers.delete()
            self.stdout.write(f'  Deleted DepartmentTeacher: {n}')

            n, _ = guardians.delete()
            self.stdout.write(f'  Deleted Guardian: {n}')

            n, _ = classrooms.delete()
            self.stdout.write(f'  Deleted ClassRoom: {n}')

            n, _ = departments.delete()
            self.stdout.write(f'  Deleted Department: {n}')

            n, _ = student_memberships.delete()
            self.stdout.write(f'  Deleted SchoolStudent: {n}')

            n, _ = teacher_memberships.delete()
            self.stdout.write(f'  Deleted SchoolTeacher: {n}')

            # Delete orphaned users (not superuser, not admin, no other school memberships)
            orphan_student_ids = [
                uid for uid in student_user_ids
                if not SchoolStudent.objects.filter(student_id=uid).exists()
            ]
            orphan_teacher_ids = [
                uid for uid in teacher_user_ids
                if not SchoolTeacher.objects.filter(teacher_id=uid).exists()
            ]
            all_orphan_ids = set(orphan_student_ids) | set(orphan_teacher_ids)

            orphan_users = CustomUser.objects.filter(
                pk__in=all_orphan_ids,
                is_superuser=False,
            )
            n, _ = orphan_users.delete()
            self.stdout.write(f'  Deleted orphaned users: {n}')

            if nuke:
                n, _ = schools.delete()
                self.stdout.write(f'  Deleted School: {n}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Done.'))
