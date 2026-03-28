"""
python manage.py setup_roles

Creates all standard Role records in the database, assigns the 'admin'
role to every superuser that lacks one, and backfills missing UserRole
records for school students and teachers based on SchoolStudent /
SchoolTeacher membership.
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

        # ── Superusers → admin role ──────────────────────────────────────────
        admin_role = Role.objects.get(name=Role.ADMIN)
        superusers = CustomUser.objects.filter(is_superuser=True)
        admin_assigned = 0
        for user in superusers:
            _, created = UserRole.objects.get_or_create(user=user, role=admin_role)
            if created:
                admin_assigned += 1
                self.stdout.write(f'  Assigned admin role → {user.username}')

        # ── Backfill: SchoolStudent → student role ───────────────────────────
        try:
            from classroom.models import SchoolStudent
            student_role = Role.objects.get(name=Role.STUDENT)
            school_students = SchoolStudent.objects.filter(
                is_active=True
            ).select_related('student')
            student_assigned = 0
            for ss in school_students:
                _, created = UserRole.objects.get_or_create(
                    user=ss.student, role=student_role
                )
                if created:
                    student_assigned += 1
            self.stdout.write(
                f'  School students: {student_assigned} given student role '
                f'({school_students.count()} total active)'
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  School student backfill skipped: {e}'))

        # ── Backfill: SchoolTeacher → teacher role ───────────────────────────
        try:
            from classroom.models import SchoolTeacher
            teacher_role = Role.objects.get(name=Role.TEACHER)
            school_teachers = SchoolTeacher.objects.filter(
                is_active=True
            ).select_related('teacher')
            teacher_assigned = 0
            for st in school_teachers:
                _, created = UserRole.objects.get_or_create(
                    user=st.teacher, role=teacher_role
                )
                if created:
                    teacher_assigned += 1
            self.stdout.write(
                f'  School teachers: {teacher_assigned} given teacher role '
                f'({school_teachers.count()} total active)'
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  School teacher backfill skipped: {e}'))

        # ── Backfill: users with subscription → individual_student role ──────
        try:
            ind_role = Role.objects.get(name=Role.INDIVIDUAL_STUDENT)
            users_with_sub = CustomUser.objects.filter(
                subscription__isnull=False,
                is_superuser=False,
            )
            ind_assigned = 0
            for user in users_with_sub:
                if not user.roles.filter(is_active=True).exists():
                    _, created = UserRole.objects.get_or_create(
                        user=user, role=ind_role
                    )
                    if created:
                        ind_assigned += 1
            self.stdout.write(
                f'  Individual students: {ind_assigned} given individual_student role'
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  Individual student backfill skipped: {e}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {len(ROLES)} roles ready, {admin_assigned} superuser(s) given admin role.'
        ))
