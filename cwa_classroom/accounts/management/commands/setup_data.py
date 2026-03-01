"""
python manage.py setup_data

Seeds the database with:
  - All Roles
  - Year levels 1–8
  - Basic Facts levels 100–132
  - Sample subjects and topics
  - Sample packages (Free, Basic, Premium)
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Role, CustomUser, UserRole


SUBJECTS = [
    ('Number', [
        'Addition & Subtraction',
        'Multiplication & Division',
        'Fractions',
        'Decimals',
        'Place Value',
        'Number Patterns',
    ]),
    ('Measurement', [
        'Length & Distance',
        'Area & Perimeter',
        'Volume & Capacity',
        'Time',
        'Mass & Weight',
        'Temperature',
    ]),
    ('Geometry', [
        '2D Shapes',
        '3D Shapes',
        'Angles',
        'Symmetry & Transformations',
        'Position & Direction',
    ]),
    ('Statistics', [
        'Graphs & Charts',
        'Probability',
        'Data Collection',
    ]),
    ('Algebra', [
        'Patterns & Sequences',
        'Equations & Expressions',
        'Ratios & Proportions',
    ]),
]

PACKAGES = [
    {'name': 'Free',    'price': 0,    'class_limit': 0,  'trial_days': 0,  'billing_type': 'recurring', 'order': 1},
    {'name': 'Basic',   'price': 9,    'class_limit': 1,  'trial_days': 14, 'billing_type': 'recurring', 'order': 2},
    {'name': 'Premium', 'price': 19,   'class_limit': 0,  'trial_days': 14, 'billing_type': 'recurring', 'order': 3},
]


class Command(BaseCommand):
    help = 'Seed database with roles, levels, subjects, topics, and packages'

    @transaction.atomic
    def handle(self, *args, **options):
        self._setup_roles()
        self._setup_levels()
        self._setup_subjects()
        self._setup_packages()
        self.stdout.write(self.style.SUCCESS('\nSetup complete! Run the server and log in.'))

    def _setup_roles(self):
        self.stdout.write('\n--- Roles ---')
        roles = [
            (Role.ADMIN,              'Admin',              'Full system access'),
            (Role.TEACHER,            'Teacher',            'Manages classes and students'),
            (Role.STUDENT,            'Student',            'Enrolled via a school/teacher'),
            (Role.INDIVIDUAL_STUDENT, 'Individual Student', 'Self-enrolled with subscription'),
            (Role.ACCOUNTANT,         'Accountant',         'Billing and finance access'),
            (Role.HEAD_OF_DEPARTMENT, 'Head of Department', 'Department-level reporting'),
        ]
        for name, display_name, description in roles:
            _, created = Role.objects.get_or_create(
                name=name,
                defaults={'display_name': display_name, 'description': description},
            )
            self.stdout.write(f'  {"✓ Created" if created else "· Exists "} Role: {name}')

        # Give admin role to all superusers
        admin_role = Role.objects.get(name=Role.ADMIN)
        for user in CustomUser.objects.filter(is_superuser=True):
            _, created = UserRole.objects.get_or_create(user=user, role=admin_role)
            if created:
                self.stdout.write(f'  ✓ Assigned admin role to superuser: {user.username}')

    def _setup_levels(self):
        from classroom.models import Level
        self.stdout.write('\n--- Levels ---')

        # Year 1–8
        for year in range(1, 9):
            _, created = Level.objects.get_or_create(
                level_number=year,
                defaults={'display_name': f'Year {year}'},
            )
            if created:
                self.stdout.write(f'  ✓ Year {year}')

        # Basic Facts levels 100–132
        subtopics = [
            ('Addition',       100, 106),
            ('Subtraction',    107, 113),
            ('Multiplication', 114, 120),
            ('Division',       121, 127),
            ('Place Value',    128, 132),
        ]
        for label, start, end in subtopics:
            for i, num in enumerate(range(start, end + 1), 1):
                display = f'{label} L{i}'
                _, created = Level.objects.get_or_create(
                    level_number=num,
                    defaults={'display_name': display},
                )
                if created:
                    self.stdout.write(f'  ✓ BF Level {num}: {display}')

        self.stdout.write(f'  Levels ready: {Level.objects.count()} total')

    def _setup_subjects(self):
        from django.utils.text import slugify
        from classroom.models import Subject, Topic, Level
        self.stdout.write('\n--- Subjects & Topics ---')

        all_levels = Level.objects.filter(level_number__lte=8)

        for subject_name, topic_names in SUBJECTS:
            subject, _ = Subject.objects.get_or_create(
                name=subject_name,
                defaults={'slug': slugify(subject_name), 'is_active': True},
            )
            for topic_name in topic_names:
                slug = slugify(topic_name)
                topic, created = Topic.objects.get_or_create(
                    name=topic_name,
                    subject=subject,
                    defaults={'slug': slug, 'is_active': True},
                )
                if created:
                    topic.levels.set(all_levels)
                    self.stdout.write(f'  ✓ {subject_name} → {topic_name}')

        total_topics = sum(len(t) for _, t in SUBJECTS)
        self.stdout.write(f'  Topics ready: {total_topics}')

    def _setup_packages(self):
        from billing.models import Package
        self.stdout.write('\n--- Packages ---')
        for p in PACKAGES:
            name = p['name']
            defaults = {k: v for k, v in p.items() if k != 'name'}
            _, created = Package.objects.get_or_create(
                name=name,
                defaults=defaults,
            )
            self.stdout.write(f'  {"✓ Created" if created else "· Exists "} Package: {name} (${p["price"]}/mo)')