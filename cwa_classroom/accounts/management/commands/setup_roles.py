"""
python manage.py setup_roles

Creates all standard Role records in the database and optionally
assigns the 'admin' role to every superuser that lacks one.
"""
from django.core.management.base import BaseCommand
from accounts.models import Role, CustomUser, UserRole


ROLES = [
    (Role.ADMIN,               'Admin',               'Full system access — manages schools and approvals'),
    (Role.SENIOR_TEACHER,      'Senior Teacher',      'Experienced teacher — approves progress criteria'),
    (Role.TEACHER,             'Teacher',             'Manages classes and students'),
    (Role.JUNIOR_TEACHER,      'Junior Teacher',      'Assistant teacher — limited permissions'),
    (Role.STUDENT,             'Student',             'Enrolled via a school/teacher'),
    (Role.INDIVIDUAL_STUDENT,  'Individual Student',  'Self-enrolled with subscription'),
    (Role.ACCOUNTANT,          'Accountant',          'Billing and finance access'),
    (Role.HEAD_OF_INSTITUTE,   'Head of Institute',   'Institute-level reporting'),
    (Role.HEAD_OF_DEPARTMENT,  'Head of Department',  'Manages a department within a school'),
    (Role.INSTITUTE_OWNER,    'Institute Owner',     'Owns and manages schools, teachers, and HoIs'),
]


class Command(BaseCommand):
    help = 'Create all standard roles and assign admin role to superusers'

    def handle(self, *args, **options):
        for name, display_name, description in ROLES:
            role, created = Role.objects.update_or_create(
                name=name,
                defaults={
                    'display_name': display_name,
                    'description': description,
                    'is_active': True,  # Always ensure active, even on existing records
                },
            )
            status = 'created' if created else 'updated'
            self.stdout.write(f'  Role "{name}" — {status}')

        admin_role = Role.objects.get(name=Role.ADMIN)
        superusers = CustomUser.objects.filter(is_superuser=True)
        assigned = 0
        for user in superusers:
            _, created = UserRole.objects.get_or_create(user=user, role=admin_role)
            if created:
                assigned += 1
                self.stdout.write(f'  Assigned admin role → {user.username}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {len(ROLES)} roles ready, {assigned} superuser(s) given admin role.'
        ))
