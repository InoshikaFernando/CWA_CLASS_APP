from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject, DepartmentTeacher,
    Subject, Level, DepartmentLevel, ClassRoom,
)


class ClassCreationTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Admin user (also institute owner for class creation)
        cls.admin_user = CustomUser.objects.create_user(
            'testadmin', 'wlhtestmails+admin@gmail.com', 'password1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.admin_user.roles.add(admin_role)
        cls.admin_user.roles.add(owner_role)

        # HoD user
        cls.hod_user = CustomUser.objects.create_user(
            'testhod', 'wlhtestmails+hod@gmail.com', 'password1!',
        )
        hod_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_DEPARTMENT,
            defaults={'display_name': 'Head of Department'},
        )
        cls.hod_user.roles.add(hod_role)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.admin_user, defaults={'role': 'admin'})
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.hod_user, defaults={'role': 'head_of_department'})

        cls.maths = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]

        # Year levels 1-9
        cls.year_levels = []
        for i in range(1, 10):
            lv, _ = Level.objects.get_or_create(
                level_number=i,
                defaults={'display_name': f'Year {i}', 'subject': cls.maths},
            )
            if not lv.subject:
                lv.subject = cls.maths
                lv.save(update_fields=['subject'])
            cls.year_levels.append(lv)

        cls.dept_maths = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths',
            head=cls.hod_user,
        )
        DepartmentSubject.objects.create(department=cls.dept_maths, subject=cls.maths)
        DepartmentTeacher.objects.create(
            department=cls.dept_maths, teacher=cls.hod_user,
        )
        DepartmentTeacher.objects.create(
            department=cls.dept_maths, teacher=cls.admin_user,
        )

        # Map Year 1-3 to department
        for lv in cls.year_levels[:3]:
            DepartmentLevel.objects.create(
                department=cls.dept_maths, level=lv, order=lv.level_number,
            )

        # Unmapped level (Year 9) — should be rejected
        cls.unmapped_level = cls.year_levels[8]


class AdminClassCreationTest(ClassCreationTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='testadmin', password='password1!')

    def test_class_inherits_subject_from_department(self):
        url = reverse('create_class')
        resp = self.client.post(url, {
            'name': 'Maths Class A',
            'department': str(self.dept_maths.id),
            'levels': [str(self.year_levels[0].id)],
        })
        self.assertEqual(resp.status_code, 302)
        cls = ClassRoom.objects.get(name='Maths Class A')
        self.assertEqual(cls.subject, self.maths)

    def test_class_uses_department_level_mappings(self):
        url = reverse('create_class')
        resp = self.client.post(url, {
            'name': 'Maths Class B',
            'department': str(self.dept_maths.id),
            'levels': [str(self.year_levels[0].id), str(self.year_levels[1].id)],
        })
        self.assertEqual(resp.status_code, 302)
        cls = ClassRoom.objects.get(name='Maths Class B')
        self.assertEqual(cls.levels.count(), 2)

    def test_unmapped_levels_rejected(self):
        """Levels not mapped via DepartmentLevel should be ignored."""
        url = reverse('create_class')
        resp = self.client.post(url, {
            'name': 'Maths Class C',
            'department': str(self.dept_maths.id),
            'levels': [str(self.unmapped_level.id), str(self.year_levels[0].id)],
        })
        cls = ClassRoom.objects.get(name='Maths Class C')
        # Only Year 1 (mapped) should be set, not Year 9 (unmapped)
        self.assertEqual(cls.levels.count(), 1)
        self.assertIn(self.year_levels[0], cls.levels.all())
        self.assertNotIn(self.unmapped_level, cls.levels.all())


class HoDClassCreationTest(ClassCreationTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='testhod', password='password1!')

    def test_hod_class_inherits_subject(self):
        url = reverse('hod_create_class')
        resp = self.client.post(url, {
            'name': 'HoD Maths A',
            'department': str(self.dept_maths.id),
            'levels': [str(self.year_levels[0].id)],
        })
        self.assertEqual(resp.status_code, 302)
        cls = ClassRoom.objects.get(name='HoD Maths A')
        self.assertEqual(cls.subject, self.maths)

    def test_hod_unmapped_levels_rejected(self):
        url = reverse('hod_create_class')
        resp = self.client.post(url, {
            'name': 'HoD Maths B',
            'department': str(self.dept_maths.id),
            'levels': [str(self.unmapped_level.id)],
        })
        cls = ClassRoom.objects.get(name='HoD Maths B')
        self.assertEqual(cls.levels.count(), 0)

    def test_hod_class_no_levels(self):
        """Class creation without selecting levels should still work."""
        url = reverse('hod_create_class')
        resp = self.client.post(url, {
            'name': 'HoD Maths C',
            'department': str(self.dept_maths.id),
        })
        self.assertEqual(resp.status_code, 302)
        cls = ClassRoom.objects.get(name='HoD Maths C')
        self.assertEqual(cls.subject, self.maths)
        self.assertEqual(cls.levels.count(), 0)
