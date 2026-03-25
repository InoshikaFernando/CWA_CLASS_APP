import json

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject, Subject, Level, DepartmentLevel,
)


class DepartmentLevelsAPITestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'testadmin', 'admin@test.com', 'pass1234',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin_user.roles.add(admin_role)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.admin_user, role='admin',
        )

        cls.maths = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.coding = Subject.objects.get_or_create(
            slug='coding',
            defaults={'name': 'Coding', 'is_active': True},
        )[0]

        # Ensure year levels exist
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
        )
        DepartmentSubject.objects.create(department=cls.dept_maths, subject=cls.maths)
        cls.dept_coding = Department.objects.create(
            school=cls.school, name='Coding', slug='coding',
        )
        DepartmentSubject.objects.create(department=cls.dept_coding, subject=cls.coding)


class DepartmentLevelsAPITest(DepartmentLevelsAPITestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='testadmin', password='pass1234')

    def test_api_returns_mapped_levels(self):
        for i, lv in enumerate(self.year_levels[:3]):
            DepartmentLevel.objects.create(
                department=self.dept_maths, level=lv, order=i + 1,
            )
        url = reverse('api_department_levels', args=[self.dept_maths.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data['levels']), 3)
        self.assertEqual(data['levels'][0]['display_name'], 'Year 1')

    def test_api_excludes_basic_facts(self):
        """Basic Facts levels (100-199) should never appear in API response."""
        # Create a basic facts level mapped to department
        bf_level, _ = Level.objects.get_or_create(
            level_number=100,
            defaults={'display_name': 'Addition L1', 'subject': self.maths},
        )
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=bf_level, order=100,
        )
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=self.year_levels[0], order=1,
        )
        url = reverse('api_department_levels', args=[self.dept_maths.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        # Only Year 1 should appear, not Addition L1
        self.assertEqual(len(data['levels']), 1)
        self.assertEqual(data['levels'][0]['display_name'], 'Year 1')

    def test_api_returns_empty_when_no_mapping(self):
        url = reverse('api_department_levels', args=[self.dept_coding.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertEqual(data['levels'], [])
        self.assertEqual(data['custom_levels'], [])

    def test_api_respects_local_display_name(self):
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=self.year_levels[1], order=1,
            local_display_name='Year 1 (AU)',
        )
        url = reverse('api_department_levels', args=[self.dept_maths.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertEqual(data['levels'][0]['display_name'], 'Year 1 (AU)')

    def test_api_separates_year_and_custom(self):
        """Year levels go in 'levels', custom (200+) go in 'custom_levels'."""
        custom_lv, _ = Level.objects.get_or_create(
            level_number=200,
            defaults={'display_name': 'Custom L1', 'school': self.school, 'subject': self.maths},
        )
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=self.year_levels[0], order=1,
        )
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=custom_lv, order=10,
        )
        url = reverse('api_department_levels', args=[self.dept_maths.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertEqual(len(data['levels']), 1)
        self.assertEqual(len(data['custom_levels']), 1)
        self.assertEqual(data['custom_levels'][0]['display_name'], 'Custom L1')

    def test_api_includes_subject_info(self):
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=self.year_levels[0], order=1,
        )
        url = reverse('api_department_levels', args=[self.dept_maths.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertTrue(len(data['subjects']) > 0)
        self.assertEqual(data['subjects'][0]['name'], 'Mathematics')

    def test_api_subject_null_for_no_subject_dept(self):
        dept_custom = Department.objects.create(
            school=self.school, name='Custom', slug='custom',
        )
        url = reverse('api_department_levels', args=[dept_custom.id])
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertEqual(data['subjects'], [])


class AutoAssignmentTest(DepartmentLevelsAPITestBase):
    """Test that creating a department with a subject auto-assigns levels via DepartmentLevel."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='testadmin', password='pass1234')

    def test_auto_assignment_on_maths_department(self):
        """Creating a Maths department should auto-create DepartmentLevel rows for Year 1-9."""
        school2 = School.objects.create(
            name='School 2', slug='school-2', admin=self.admin_user,
        )
        new_dept = Department.objects.create(
            school=school2, name='Maths', slug='maths',
        )
        DepartmentSubject.objects.create(department=new_dept, subject=self.maths)
        # Simulate what DepartmentCreateView does
        subject_levels = Level.objects.filter(
            subject=self.maths, school__isnull=True,
        ).exclude(level_number__gte=100, level_number__lt=200)
        for lv in subject_levels:
            DepartmentLevel.objects.get_or_create(
                department=new_dept, level=lv,
                defaults={'order': lv.level_number},
            )
        count = DepartmentLevel.objects.filter(department=new_dept).count()
        self.assertEqual(count, 9)  # Year 1-9

    def test_auto_assignment_idempotent(self):
        """Running auto-assignment twice should not create duplicates."""
        subject_levels = Level.objects.filter(
            subject=self.maths, school__isnull=True,
        ).exclude(level_number__gte=100, level_number__lt=200)
        # First pass
        for lv in subject_levels:
            DepartmentLevel.objects.get_or_create(
                department=self.dept_maths, level=lv,
                defaults={'order': lv.level_number},
            )
        count1 = DepartmentLevel.objects.filter(department=self.dept_maths).count()
        # Second pass (idempotent)
        for lv in subject_levels:
            DepartmentLevel.objects.get_or_create(
                department=self.dept_maths, level=lv,
                defaults={'order': lv.level_number},
            )
        count2 = DepartmentLevel.objects.filter(department=self.dept_maths).count()
        self.assertEqual(count1, count2)

    def test_no_auto_assignment_for_non_maths(self):
        """Creating a Coding department should not auto-assign Maths year levels."""
        # The auto-assignment only assigns levels matching the department's subject
        subject_levels = Level.objects.filter(
            subject=self.coding, school__isnull=True,
        ).exclude(level_number__gte=100, level_number__lt=200)
        for lv in subject_levels:
            DepartmentLevel.objects.get_or_create(
                department=self.dept_coding, level=lv,
                defaults={'order': lv.level_number},
            )
        # Coding has no global levels assigned, so count should be 0
        count = DepartmentLevel.objects.filter(department=self.dept_coding).count()
        self.assertEqual(count, 0)
