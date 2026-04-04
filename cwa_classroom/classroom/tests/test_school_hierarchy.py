from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentTeacher,
    DepartmentSubject, Subject, Level, ClassRoom, ClassTeacher,
)


class SchoolHierarchyTestBase(TestCase):
    """Shared setup for hierarchy view tests."""

    @classmethod
    def setUpTestData(cls):
        # ── Roles ────────────────────────────────────────────
        cls.role_admin, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.role_hoi, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        cls.role_hod, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_DEPARTMENT,
            defaults={'display_name': 'Head of Department'},
        )
        cls.role_senior, _ = Role.objects.get_or_create(
            name=Role.SENIOR_TEACHER,
            defaults={'display_name': 'Senior Teacher'},
        )
        cls.role_teacher, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.role_junior, _ = Role.objects.get_or_create(
            name=Role.JUNIOR_TEACHER,
            defaults={'display_name': 'Junior Teacher'},
        )
        cls.role_student, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        # ── Users ────────────────────────────────────────────
        cls.admin_user = CustomUser.objects.create_user(
            'admin', 'admin@test.com', 'pass1234',
            first_name='Admin', last_name='User',
        )
        cls.admin_user.roles.add(cls.role_admin)

        cls.hoi_user = CustomUser.objects.create_user(
            'hoi', 'hoi@test.com', 'pass1234',
            first_name='Head', last_name='Institute',
        )
        cls.hoi_user.roles.add(cls.role_hoi)

        cls.hod_user = CustomUser.objects.create_user(
            'hod', 'hod@test.com', 'pass1234',
            first_name='Head', last_name='Dept',
        )
        cls.hod_user.roles.add(cls.role_hod)

        cls.teacher_a = CustomUser.objects.create_user(
            'teacher_a', 'ta@test.com', 'pass1234',
            first_name='Alice', last_name='Teacher',
        )
        cls.teacher_a.roles.add(cls.role_senior)

        cls.teacher_b = CustomUser.objects.create_user(
            'teacher_b', 'tb@test.com', 'pass1234',
            first_name='Bob', last_name='Teacher',
        )
        cls.teacher_b.roles.add(cls.role_teacher)

        cls.student_user = CustomUser.objects.create_user(
            'student', 'student@test.com', 'pass1234',
        )
        cls.student_user.roles.add(cls.role_student)

        # ── School ───────────────────────────────────────────
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.hoi_user, defaults={'role': 'head_of_institute'})
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.hod_user, defaults={'role': 'head_of_department'})
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.teacher_a, defaults={'role': 'senior_teacher'})
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.teacher_b, defaults={'role': 'teacher'})

        # ── Subject & Department ─────────────────────────────
        cls.maths, _ = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.dept = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths',
            head=cls.hod_user,
        )
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.maths)
        DepartmentTeacher.objects.create(
            department=cls.dept, teacher=cls.teacher_a,
        )
        DepartmentTeacher.objects.create(
            department=cls.dept, teacher=cls.teacher_b,
        )

        # ── Classes ──────────────────────────────────────────
        cls.class_solo = ClassRoom.objects.create(
            name='Maths Year 7 Mon', school=cls.school,
            department=cls.dept, subject=cls.maths,
        )
        ClassTeacher.objects.create(
            classroom=cls.class_solo, teacher=cls.teacher_a,
        )

        # Shared class (taught by both teacher_a and teacher_b)
        cls.class_shared = ClassRoom.objects.create(
            name='Maths Year 8 Wed', school=cls.school,
            department=cls.dept, subject=cls.maths,
        )
        ClassTeacher.objects.create(
            classroom=cls.class_shared, teacher=cls.teacher_a,
        )
        ClassTeacher.objects.create(
            classroom=cls.class_shared, teacher=cls.teacher_b,
        )


class SchoolHierarchyAccessTests(SchoolHierarchyTestBase):
    """Test role-based access control for hierarchy page."""

    def test_admin_can_access(self):
        self.client.login(username='admin', password='pass1234')
        resp = self.client.get(
            reverse('school_hierarchy', args=[self.school.id]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_hoi_can_access(self):
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(
            reverse('school_hierarchy', args=[self.school.id]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access(self):
        self.client.login(username='hod', password='pass1234')
        resp = self.client.get(
            reverse('school_hierarchy', args=[self.school.id]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_student_cannot_access(self):
        self.client.login(username='student', password='pass1234')
        resp = self.client.get(
            reverse('school_hierarchy', args=[self.school.id]),
        )
        # Should redirect (permission denied)
        self.assertEqual(resp.status_code, 302)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(
            reverse('school_hierarchy', args=[self.school.id]),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)


class SchoolHierarchyContentTests(SchoolHierarchyTestBase):
    """Test the hierarchy page content."""

    def setUp(self):
        self.client.login(username='admin', password='pass1234')
        self.resp = self.client.get(
            reverse('school_hierarchy', args=[self.school.id]),
        )

    def test_school_name_shown(self):
        self.assertContains(self.resp, 'Test School')

    def test_hoi_shown(self):
        self.assertContains(self.resp, 'Head Institute')
        self.assertContains(self.resp, 'Head of Institute')

    def test_department_shown(self):
        self.assertContains(self.resp, 'Mathematics')

    def test_hod_shown(self):
        self.assertContains(self.resp, 'Head Dept')

    def test_teachers_shown(self):
        self.assertContains(self.resp, 'Alice Teacher')
        self.assertContains(self.resp, 'Bob Teacher')

    def test_classes_shown(self):
        self.assertContains(self.resp, 'Maths Year 7 Mon')
        self.assertContains(self.resp, 'Maths Year 8 Wed')

    def test_shared_class_marked(self):
        # Shared class should have "(shared)" label
        self.assertContains(self.resp, '(shared)')

    def test_solo_class_not_marked_shared(self):
        # Count occurrences — shared class appears for both teachers
        content = self.resp.content.decode()
        # "Maths Year 7 Mon" should appear without shared styling
        solo_idx = content.index('Maths Year 7 Mon')
        # There should be no "(shared)" near the solo class
        nearby = content[solo_idx:solo_idx + 200]
        self.assertNotIn('(shared)', nearby)


class SchoolHierarchyAutoRedirectTests(SchoolHierarchyTestBase):
    """Test the auto-redirect URL (no school_id)."""

    def test_single_school_auto_redirects(self):
        self.client.login(username='admin', password='pass1234')
        resp = self.client.get(reverse('school_hierarchy_auto'))
        # Should render directly (not redirect), because user has 1 school
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test School')

    def test_multi_school_shows_picker(self):
        school2 = School.objects.create(
            name='Second School', slug='second-school',
            admin=self.admin_user,
        )
        self.client.login(username='admin', password='pass1234')
        resp = self.client.get(reverse('school_hierarchy_auto'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Select School')
        self.assertContains(resp, 'Test School')
        self.assertContains(resp, 'Second School')
