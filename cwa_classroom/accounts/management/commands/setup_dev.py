"""
Management command: python manage.py setup_dev

Creates all roles, test users, packages, levels, subjects and topics
so the app is immediately usable after migrate.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

TOPIC_MAPPING = {
    "Algebra": [
        "BODMAS",
        "Integers",
        "Expanding and Factorising Quadratics",
        "Linear Equations",
        "Simultaneous Equations",
        "Indices and Powers",
        "Factorising Harder Quadratics",
        "Quadratic Formula",
        "Completing the Square",
    ],
    "Geometry": [
        "Angles",
        "Trigonometry",
        "Pythagoras' Theorem",
        "Circles",
        "Composite Areas",
    ],
    "Measurement": [
        "Measurements",
        "Date and Time",
        "Area",
        "Perimeter",
        "Volume",
        "Rates",
        "Unit Conversion",
    ],
    "Number": [
        "Whole Numbers",
        "Place Values",
        "Fractions",
        "Multiplication",
        "Division",
        "Finance",
        "Factors",
        "Prime Numbers",
        "Square and Triangular Numbers",
        "Square Roots",
        "Operation Order",
        "Number Systems",
        "Addition and Subtraction",
        "Estimation and Rounding",
        "Ratios",
        "Logic and Problem Solving",
    ],
    "Space": [
        "3D Shapes",
    ],
    "Statistics": [
        "Mean and Average",
        "Probability",
        "Data Interpretation",
    ],
}


class Command(BaseCommand):
    help = 'Bootstrap dev database with roles, users, packages, levels and topics.'

    def handle(self, *args, **options):
        with transaction.atomic():
            self._create_roles()
            self._create_packages()
            self._create_levels()
            self._create_subjects_and_topics()
            self._create_users()
        self.stdout.write(self.style.SUCCESS('\n✅  Dev setup complete! Login at /accounts/login/'))
        self.stdout.write('  admin / admin123')
        self.stdout.write('  teacher1 / teacher123')
        self.stdout.write('  student1 / student123')
        self.stdout.write('  indstudent1 / student123\n')

    # ------------------------------------------------------------------
    def _create_roles(self):
        from accounts.models import Role
        roles = [
            ('admin', 'Admin'),
            ('teacher', 'Teacher'),
            ('student', 'Student'),
            ('individual_student', 'Individual Student'),
            ('accountant', 'Accountant'),
            ('head_of_department', 'Head of Department'),
        ]
        for name, display in roles:
            Role.objects.get_or_create(name=name, defaults={'display_name': display, 'is_active': True})
        self.stdout.write(f'  Roles: {len(roles)} created/verified')

    def _create_packages(self):
        from billing.models import Package
        packages = [
            ('1 Class', 1, '9.99', 14),
            ('3 Classes', 3, '19.99', 14),
            ('5 Classes', 5, '29.99', 14),
            ('Unlimited', 0, '49.99', 14),
        ]
        for name, limit, price, trial in packages:
            Package.objects.get_or_create(
                name=name,
                defaults={'class_limit': limit, 'price': price, 'trial_days': trial, 'is_active': True}
            )
        self.stdout.write(f'  Packages: {len(packages)} created/verified')

    def _create_levels(self):
        from classroom.models import Level
        # Year levels 1-8
        for y in range(1, 9):
            Level.objects.get_or_create(level_number=y, defaults={'display_name': f'Year {y}'})
        # Basic Facts levels
        bf_levels = [
            (100, 'Addition Level 1'), (101, 'Addition Level 2'), (102, 'Addition Level 3'),
            (103, 'Addition Level 4'), (104, 'Addition Level 5'), (105, 'Addition Level 6'),
            (106, 'Addition Level 7'),
            (107, 'Subtraction Level 1'), (108, 'Subtraction Level 2'), (109, 'Subtraction Level 3'),
            (110, 'Subtraction Level 4'), (111, 'Subtraction Level 5'), (112, 'Subtraction Level 6'),
            (113, 'Subtraction Level 7'),
            (114, 'Multiplication Level 1'), (115, 'Multiplication Level 2'), (116, 'Multiplication Level 3'),
            (117, 'Multiplication Level 4'), (118, 'Multiplication Level 5'), (119, 'Multiplication Level 6'),
            (120, 'Multiplication Level 7'),
            (121, 'Division Level 1'), (122, 'Division Level 2'), (123, 'Division Level 3'),
            (124, 'Division Level 4'), (125, 'Division Level 5'), (126, 'Division Level 6'),
            (127, 'Division Level 7'),
            (128, 'Place Value Level 1'), (129, 'Place Value Level 2'), (130, 'Place Value Level 3'),
            (131, 'Place Value Level 4'), (132, 'Place Value Level 5'),
        ]
        for num, name in bf_levels:
            Level.objects.get_or_create(level_number=num, defaults={'display_name': name})
        self.stdout.write(f'  Levels: {8 + len(bf_levels)} created/verified')

    def _create_subjects_and_topics(self):
        from classroom.models import Subject, Topic, Level
        from django.utils.text import slugify

        maths, _ = Subject.objects.get_or_create(
            name='Mathematics', defaults={'slug': 'mathematics', 'is_active': True}
        )

        # subtopic name → list of year level numbers
        topic_map = {
            'Measurements':    [2, 3, 5, 6, 7],
            'Whole Numbers':   [6],
            'Factors':         [6, 7, 8],
            'Angles':          [6],
            'Place Values':                  [2, 4, 7],
            'Fractions':       [3, 4, 7, 8],
            'BODMAS':          [5, 6, 7],
            'Date and Time':   [3],
            'Finance':         [3, 4],
            'Integers':        [4, 7, 8],
            'Trigonometry':    [8],
            'Multiplication':                 [1, 2, 3, 4, 7],
            'Division':                      [1, 2, 3, 4, 7],
            'Prime Numbers':                 [7],
            'Square and Triangular Numbers': [7],
            'Square Roots':                  [7],
            'Operation Order':               [7],
            'Number Systems':                [7],
            'Addition and Subtraction':      [7],
            'Estimation and Rounding':                 [7],
            'Expanding and Factorising Quadratics':    [7],
            # Number additions
            'Ratios':                                  [7],
            'Logic and Problem Solving':               [7],
            # Measurement additions
            'Area':                                    [7],
            'Perimeter':                               [7],
            'Volume':                                  [8],
            'Rates':                                   [7, 8],
            'Unit Conversion':                         [7],
            # Algebra additions
            'Linear Equations':                        [8],
            'Simultaneous Equations':                  [8],
            'Indices and Powers':                      [7, 8],
            'Factorising Harder Quadratics':           [7],
            'Quadratic Formula':                       [7],
            'Completing the Square':                   [8],
            # Geometry additions
            "Pythagoras' Theorem":                     [8],
            'Circles':                                 [8],
            'Composite Areas':                         [8],
            # Space
            '3D Shapes':                               [7],
            # Statistics
            'Mean and Average':                        [7],
            'Probability':                             [7],
            'Data Interpretation':                     [7],
        }

        subtopic_count = 0
        for strand_order, (strand_name, subtopic_names) in enumerate(TOPIC_MAPPING.items()):
            strand, _ = Topic.objects.get_or_create(
                subject=maths, slug=slugify(strand_name),
                defaults={'name': strand_name, 'order': strand_order, 'is_active': True, 'parent': None},
            )
            for sub_order, sub_name in enumerate(subtopic_names):
                subtopic, _ = Topic.objects.get_or_create(
                    subject=maths, slug=slugify(sub_name),
                    defaults={'name': sub_name, 'order': sub_order, 'is_active': True, 'parent': strand},
                )
                if subtopic.parent_id != strand.id:
                    subtopic.parent = strand
                    subtopic.save(update_fields=['parent'])
                for y in topic_map.get(sub_name, []):
                    level = Level.objects.filter(level_number=y).first()
                    if level:
                        subtopic.levels.add(level)
                subtopic_count += 1
        self.stdout.write(f'  Strands: {len(TOPIC_MAPPING)} | Subtopics: {subtopic_count} created/verified')

    def _create_users(self):
        from accounts.models import CustomUser, Role, UserRole
        from billing.models import Package, Subscription
        from classroom.models import ClassRoom, ClassTeacher, ClassStudent, Level
        from django.utils import timezone
        from datetime import timedelta

        def make_user(username, password, role_name, **kwargs):
            user, created = CustomUser.objects.get_or_create(
                username=username, defaults={'email': f'{username}@dev.local', **kwargs}
            )
            if created:
                user.set_password(password)
                user.save()
            role = Role.objects.get(name=role_name)
            UserRole.objects.get_or_create(user=user, role=role)
            return user, created

        # Admin
        admin, _ = make_user('admin', 'admin123', 'admin', is_staff=True, is_superuser=True)

        # Teacher
        teacher, _ = make_user('teacher1', 'teacher123', 'teacher')

        # Student
        student, _ = make_user('student1', 'student123', 'student')

        # Individual Student
        package = Package.objects.filter(name='3 Classes').first()
        ind_student, created = make_user('indstudent1', 'student123', 'individual_student', package=package)
        if created and package:
            Subscription.objects.get_or_create(
                user=ind_student,
                defaults={
                    'package': package,
                    'status': 'trialing',
                    'trial_end': timezone.now() + timedelta(days=14),
                }
            )

        # Create a demo class with teacher + student
        year3 = Level.objects.filter(level_number=3).first()
        year4 = Level.objects.filter(level_number=4).first()
        classroom, _ = ClassRoom.objects.get_or_create(
            name='Demo Class 3/4',
            defaults={'created_by': teacher}
        )
        if year3: classroom.levels.add(year3)
        if year4: classroom.levels.add(year4)
        ClassTeacher.objects.get_or_create(classroom=classroom, teacher=teacher)
        ClassStudent.objects.get_or_create(classroom=classroom, student=student)
        ClassStudent.objects.get_or_create(classroom=classroom, student=ind_student)

        self.stdout.write('  Users: admin, teacher1, student1, indstudent1 created/verified')
        self.stdout.write(f'  Demo class: "{classroom.name}" ({classroom.code})')
