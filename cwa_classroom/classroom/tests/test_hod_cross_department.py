"""
Tests that a Head of Department who also teaches in other departments
can access classes in those departments (not just their own).
"""
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentTeacher,
    DepartmentSubject, Subject, ClassRoom, ClassTeacher, ClassStudent,
)


class HoDCrossDepartmentTestBase(TestCase):
    """
    Setup: one school, two departments (Maths headed by hod_user, IT headed
    by another user).  hod_user also teaches an IT class.
    """

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.hod_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_DEPARTMENT, defaults={'display_name': 'Head of Department'},
        )
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )

        # Admin / owner
        cls.admin_user = CustomUser.objects.create_user(
            'testadmin', 'admin@test.com', 'pass1234',
        )
        cls.admin_user.roles.add(cls.admin_role, cls.owner_role)

        # HoD user (heads Maths, teaches IT)
        cls.hod_user = CustomUser.objects.create_user(
            'testhod', 'hod@test.com', 'pass1234',
        )
        cls.hod_user.roles.add(cls.hod_role)

        # Another HoD who heads IT
        cls.it_head = CustomUser.objects.create_user(
            'ithead', 'ithead@test.com', 'pass1234',
        )
        cls.it_head.roles.add(cls.hod_role)

        # A plain teacher (should NOT access classes they don't teach)
        cls.other_teacher = CustomUser.objects.create_user(
            'otherteacher', 'other@test.com', 'pass1234',
        )
        cls.other_teacher.roles.add(cls.teacher_role)

        # School
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        for u in [cls.admin_user, cls.hod_user, cls.it_head, cls.other_teacher]:
            SchoolTeacher.objects.create(school=cls.school, teacher=u, role='teacher')

        # Subjects
        cls.maths_subject, _ = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.it_subject, _ = Subject.objects.get_or_create(
            slug='information-technology', defaults={'name': 'Information Technology', 'is_active': True},
        )

        # Departments
        cls.dept_maths = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths', head=cls.hod_user,
        )
        cls.dept_it = Department.objects.create(
            school=cls.school, name='Information Technology', slug='it', head=cls.it_head,
        )
        DepartmentSubject.objects.create(department=cls.dept_maths, subject=cls.maths_subject)
        DepartmentSubject.objects.create(department=cls.dept_it, subject=cls.it_subject)
        DepartmentTeacher.objects.create(department=cls.dept_maths, teacher=cls.hod_user)
        DepartmentTeacher.objects.create(department=cls.dept_it, teacher=cls.it_head)
        DepartmentTeacher.objects.create(department=cls.dept_it, teacher=cls.hod_user)

        # Classes
        cls.maths_class = ClassRoom.objects.create(
            name='Maths 01', school=cls.school, department=cls.dept_maths,
            subject=cls.maths_subject, day='monday', start_time='09:00',
        )
        cls.it_class = ClassRoom.objects.create(
            name='Web Dev 01', school=cls.school, department=cls.dept_it,
            subject=cls.it_subject, day='tuesday', start_time='10:00',
        )
        cls.other_it_class = ClassRoom.objects.create(
            name='IT Fundamentals', school=cls.school, department=cls.dept_it,
            subject=cls.it_subject, day='wednesday', start_time='11:00',
        )

        # hod_user teaches maths_class and it_class (but NOT other_it_class)
        ClassTeacher.objects.create(classroom=cls.maths_class, teacher=cls.hod_user)
        ClassTeacher.objects.create(classroom=cls.it_class, teacher=cls.hod_user)

        # it_head teaches other_it_class
        ClassTeacher.objects.create(classroom=cls.other_it_class, teacher=cls.it_head)

        # A student for fee/remove tests
        cls.student = CustomUser.objects.create_user(
            'teststudent', 'student@test.com', 'pass1234',
        )
        ClassStudent.objects.create(classroom=cls.maths_class, student=cls.student)
        ClassStudent.objects.create(classroom=cls.it_class, student=cls.student)

    def setUp(self):
        self.client = Client()


class TestHoDClassDetailCrossDepartment(HoDCrossDepartmentTestBase):
    """ClassDetailView: HoD can access classes in own dept AND teaching classes in other depts."""

    def test_hod_can_access_own_department_class(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('class_detail', args=[self.maths_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access_teaching_class_in_other_department(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('class_detail', args=[self.it_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_cannot_access_non_teaching_class_in_other_department(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('class_detail', args=[self.other_it_class.id]))
        self.assertEqual(resp.status_code, 404)

    def test_plain_teacher_cannot_access_class_they_dont_teach(self):
        self.client.login(username='otherteacher', password='pass1234')
        resp = self.client.get(reverse('class_detail', args=[self.maths_class.id]))
        self.assertEqual(resp.status_code, 404)


class TestHoDEditClassCrossDepartment(HoDCrossDepartmentTestBase):
    """EditClassView: HoD can edit classes they teach in other departments."""

    def test_hod_can_edit_own_department_class(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('edit_class', args=[self.maths_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_edit_teaching_class_in_other_department(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('edit_class', args=[self.it_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_cannot_edit_non_teaching_class_in_other_department(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('edit_class', args=[self.other_it_class.id]))
        self.assertEqual(resp.status_code, 404)


class TestHoDAttendanceCrossDepartment(HoDCrossDepartmentTestBase):
    """ClassAttendanceView: HoD can access attendance for teaching classes in other departments."""

    def test_hod_can_access_attendance_own_department(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('class_attendance', args=[self.maths_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access_attendance_other_department_teaching(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('class_attendance', args=[self.it_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_cannot_access_attendance_other_department_not_teaching(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('class_attendance', args=[self.other_it_class.id]))
        self.assertEqual(resp.status_code, 404)


class TestHoDAssignStudentsCrossDepartment(HoDCrossDepartmentTestBase):
    """AssignStudentsView: HoD can assign students to teaching classes in other departments."""

    def test_hod_can_access_assign_students_own_department(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('assign_students', args=[self.maths_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access_assign_students_other_department_teaching(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('assign_students', args=[self.it_class.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_cannot_access_assign_students_other_department_not_teaching(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('assign_students', args=[self.other_it_class.id]))
        self.assertEqual(resp.status_code, 404)


class TestHoDDashboardCrossDepartment(HoDCrossDepartmentTestBase):
    """HoD dashboard should show classes from own department AND teaching classes from other departments."""

    def test_hod_overview_includes_other_department_teaching_classes(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Maths 01', content)
        self.assertIn('Web Dev 01', content)

    def test_hod_overview_excludes_non_teaching_other_department_classes(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('hod_overview'))
        content = resp.content.decode()
        self.assertNotIn('IT Fundamentals', content)

    def test_hod_manage_classes_includes_other_department_teaching_classes(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Maths 01', content)
        self.assertIn('Web Dev 01', content)

    def test_hod_manage_classes_excludes_non_teaching_other_department_classes(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.get(reverse('hod_manage_classes'))
        content = resp.content.decode()
        self.assertNotIn('IT Fundamentals', content)


class TestHoDRemoveStudentCrossDepartment(HoDCrossDepartmentTestBase):
    """ClassStudentRemoveView: HoD can remove students from teaching classes in other depts."""

    def test_hod_can_remove_student_from_own_department_class(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.post(reverse('class_student_remove', args=[self.maths_class.id, self.student.id]))
        self.assertIn(resp.status_code, [200, 302])

    def test_hod_can_remove_student_from_other_department_teaching_class(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.post(reverse('class_student_remove', args=[self.it_class.id, self.student.id]))
        self.assertIn(resp.status_code, [200, 302])

    def test_hod_cannot_remove_student_from_non_teaching_other_department_class(self):
        self.client.login(username='testhod', password='pass1234')
        resp = self.client.post(reverse('class_student_remove', args=[self.other_it_class.id, self.student.id]))
        self.assertEqual(resp.status_code, 404)
