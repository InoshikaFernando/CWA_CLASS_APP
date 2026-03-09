"""
Management command to remove all staff users and their related records.

Usage:
    python manage.py clear_staff            # dry-run (shows what would be deleted)
    python manage.py clear_staff --confirm  # actually delete
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from accounts.models import CustomUser, Role, UserRole
from classroom.models import SchoolTeacher, School


STAFF_ROLES = [
    Role.INSTITUTE_OWNER,
    Role.HEAD_OF_INSTITUTE,
    Role.HEAD_OF_DEPARTMENT,
    Role.SENIOR_TEACHER,
    Role.TEACHER,
    Role.JUNIOR_TEACHER,
]


def _table_exists(model):
    """Return True if the DB table for *model* exists."""
    return model._meta.db_table in connection.introspection.table_names()


class Command(BaseCommand):
    help = 'Remove all staff/teacher users and their related records (SchoolTeacher, DepartmentTeacher, Schools).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually delete. Without this flag the command only shows a dry-run.',
        )
        parser.add_argument(
            '--keep-schools',
            action='store_true',
            help='Keep School records (only delete users and memberships).',
        )

    def handle(self, *args, **options):
        confirm = options['confirm']
        keep_schools = options['keep_schools']

        # Lazy-import DepartmentTeacher so the command still works when the
        # table hasn't been migrated yet.
        DepartmentTeacher = None
        try:
            from classroom.models import DepartmentTeacher as _DT
            if _table_exists(_DT):
                DepartmentTeacher = _DT
        except ImportError:
            pass

        # Find all users who have at least one staff role
        staff_users = CustomUser.objects.filter(
            roles__name__in=STAFF_ROLES,
        ).distinct()

        # Exclude superusers / admin-role users so we don't accidentally nuke admins
        admin_users = CustomUser.objects.filter(
            roles__name=Role.ADMIN,
        ).values_list('id', flat=True)
        staff_users = staff_users.exclude(id__in=admin_users).exclude(is_superuser=True)

        staff_ids = list(staff_users.values_list('id', flat=True))

        # Gather counts (skip tables that don't exist yet)
        school_teacher_count = (
            SchoolTeacher.objects.filter(teacher_id__in=staff_ids).count()
            if _table_exists(SchoolTeacher) else 0
        )
        dept_teacher_count = (
            DepartmentTeacher.objects.filter(teacher_id__in=staff_ids).count()
            if DepartmentTeacher else 0
        )
        user_role_count = UserRole.objects.filter(
            user_id__in=staff_ids, role__name__in=STAFF_ROLES,
        ).count()
        school_count = (
            School.objects.filter(admin_id__in=staff_ids).count()
            if _table_exists(School) else 0
        )

        self.stdout.write(self.style.WARNING('\n=== Staff Cleanup ==='))
        self.stdout.write(f'  Staff users found:        {len(staff_ids)}')

        if staff_ids:
            usernames = staff_users.values_list('username', flat=True)
            for uname in usernames:
                self.stdout.write(f'    - {uname}')

        self.stdout.write(f'  SchoolTeacher records:    {school_teacher_count}')
        self.stdout.write(f'  DepartmentTeacher records:{dept_teacher_count}')
        self.stdout.write(f'  UserRole records:         {user_role_count}')
        self.stdout.write(f'  Schools owned by staff:   {school_count}')

        if not staff_ids:
            self.stdout.write(self.style.SUCCESS('\nNo staff users to delete. Done.'))
            return

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                '\nDry-run — nothing deleted. Run with --confirm to delete.'
            ))
            return

        with transaction.atomic():
            # 1. Remove department memberships (if table exists)
            if DepartmentTeacher:
                d1, _ = DepartmentTeacher.objects.filter(teacher_id__in=staff_ids).delete()
                self.stdout.write(f'  Deleted {d1} DepartmentTeacher records.')

            # 2. Remove school memberships (if table exists)
            if _table_exists(SchoolTeacher):
                d2, _ = SchoolTeacher.objects.filter(teacher_id__in=staff_ids).delete()
                self.stdout.write(f'  Deleted {d2} SchoolTeacher records.')

            # 3. Remove schools (unless --keep-schools)
            if not keep_schools and _table_exists(School):
                d3, _ = School.objects.filter(admin_id__in=staff_ids).delete()
                self.stdout.write(f'  Deleted {d3} School records.')

            # 4. Delete the user accounts (cascades UserRole, etc.)
            d4, _ = CustomUser.objects.filter(id__in=staff_ids).delete()
            self.stdout.write(f'  Deleted {d4} user-related records (users + cascaded rows).')

        self.stdout.write(self.style.SUCCESS('\nAll staff cleared successfully.'))
