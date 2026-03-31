"""
End-to-end tests for the full school-setup flow:
creating a school, adding departments/subjects, managing teachers and students,
and configuring classrooms with levels.
"""

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject, DepartmentTeacher,
    Subject, Level, DepartmentLevel, ClassRoom, ClassTeacher, ClassStudent,
    SchoolStudent,
)


def _create_role(name, display_name=None):
    """Helper: get-or-create a Role row."""
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='testpass123', **kwargs):
    """Helper: create a CustomUser."""
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'{username}@example.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    """Helper: assign a role to a user."""
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


# ---------------------------------------------------------------------------
# 1. SchoolCreationTest
# ---------------------------------------------------------------------------

class SchoolCreationTest(TestCase):
    """Test creating a school via the admin dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = _create_user('admin_owner', first_name='Admin', last_name='Owner')
        _assign_role(cls.admin_user, Role.ADMIN)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    # -- tests ---------------------------------------------------------------

    def test_create_school_via_form(self):
        """POST to admin_school_create creates a School and redirects to its detail page."""
        url = reverse('admin_school_create')
        data = {
            'name': 'Greenfield Academy',
            'address': '123 Elm Street',
            'phone': '021-555-0100',
            'email': 'info@greenfield.school.nz',
        }
        response = self.client.post(url, data)

        school = School.objects.get(name='Greenfield Academy')
        self.assertRedirects(response, reverse('admin_school_detail', kwargs={'school_id': school.id}))
        self.assertEqual(school.admin, self.admin_user)
        self.assertEqual(school.address, '123 Elm Street')
        self.assertTrue(school.slug)  # auto-generated slug
        self.assertTrue(school.is_active)

    def test_school_appears_on_dashboard(self):
        """After creation the school is listed on the admin dashboard."""
        School.objects.create(name='Dashboard School', slug='dashboard-school', admin=self.admin_user)

        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard School')

    def test_create_school_missing_name_fails(self):
        """Submitting the form without a name re-renders the form with an error."""
        url = reverse('admin_school_create')
        response = self.client.post(url, {'name': '', 'address': '456 Oak Rd'})

        # Should stay on the same page (200, re-rendered form)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(School.objects.count(), 0)


# ---------------------------------------------------------------------------
# 2. DepartmentSetupTest
# ---------------------------------------------------------------------------

class DepartmentSetupTest(TestCase):
    """Test creating departments and linking subjects to them."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = _create_user('dept_admin', first_name='Dept', last_name='Admin')
        _assign_role(cls.admin_user, Role.ADMIN)

        cls.school = School.objects.create(
            name='Lincoln High', slug='lincoln-high', admin=cls.admin_user,
        )
        cls.maths_subject = Subject.objects.create(
            name='Mathematics', slug='mathematics', is_active=True,
        )
        cls.science_subject = Subject.objects.create(
            name='Science', slug='science', is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    # -- tests ---------------------------------------------------------------

    def test_create_department(self):
        """POST to admin_department_create creates a department under the school."""
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        data = {
            'name': 'Maths Department',
            'description': 'All things numbers',
            'subjects': [str(self.maths_subject.id)],
        }
        response = self.client.post(url, data)

        dept = Department.objects.get(school=self.school, name='Maths Department')
        self.assertEqual(dept.description, 'All things numbers')
        self.assertTrue(dept.slug)
        # Should redirect to department detail
        self.assertEqual(response.status_code, 302)

    def test_department_appears_on_school_detail(self):
        """The school detail page lists the school's departments."""
        Department.objects.create(
            school=self.school, name='English Dept', slug='english-dept',
        )
        url = reverse('admin_school_detail', kwargs={'school_id': self.school.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'English Dept')

    def test_link_subject_to_department(self):
        """DepartmentSubject M2M link connects a subject to a department."""
        dept = Department.objects.create(
            school=self.school, name='Science Dept', slug='science-dept',
        )
        ds = DepartmentSubject.objects.create(
            department=dept, subject=self.science_subject, order=0,
        )
        self.assertEqual(ds.department, dept)
        self.assertEqual(ds.subject, self.science_subject)
        # Department.subjects M2M should reflect it
        self.assertIn(self.science_subject, dept.subjects.all())


# ---------------------------------------------------------------------------
# 3. TeacherManagementTest
# ---------------------------------------------------------------------------

class TeacherManagementTest(TestCase):
    """Test adding teachers to schools and departments, and verifying roles."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = _create_user('teacher_admin')
        _assign_role(cls.admin_user, Role.ADMIN)

        cls.school = School.objects.create(
            name='Teacher Test School', slug='teacher-test-school', admin=cls.admin_user,
        )
        cls.department = Department.objects.create(
            school=cls.school, name='Art Dept', slug='art-dept',
        )

        cls.teacher_user = _create_user(
            'jane_teacher', first_name='Jane', last_name='Smith',
        )
        _assign_role(cls.teacher_user, Role.TEACHER)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    # -- tests ---------------------------------------------------------------

    def test_add_teacher_to_school(self):
        """Creating a SchoolTeacher links the teacher to the school."""
        st = SchoolTeacher.objects.create(
            school=self.school,
            teacher=self.teacher_user,
            role='teacher',
        )
        self.assertEqual(st.school, self.school)
        self.assertEqual(st.teacher, self.teacher_user)
        self.assertEqual(st.role, 'teacher')
        self.assertTrue(st.is_active)

    def test_add_teacher_to_department(self):
        """Creating a DepartmentTeacher links the teacher to a department."""
        # First link teacher to school
        SchoolTeacher.objects.create(
            school=self.school, teacher=self.teacher_user, role='teacher',
        )
        dt = DepartmentTeacher.objects.create(
            department=self.department, teacher=self.teacher_user,
        )
        self.assertEqual(dt.department, self.department)
        self.assertEqual(dt.teacher, self.teacher_user)

    def test_teacher_has_correct_role(self):
        """A user assigned the TEACHER role is recognised by has_role()."""
        self.assertTrue(self.teacher_user.has_role(Role.TEACHER))
        self.assertFalse(self.teacher_user.has_role(Role.ADMIN))
        self.assertTrue(self.teacher_user.is_any_teacher)


# ---------------------------------------------------------------------------
# 4. StudentManagementTest
# ---------------------------------------------------------------------------

class StudentManagementTest(TestCase):
    """Test student registration, joining a class by code, and enrollment status."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = _create_user('student_admin')
        _assign_role(cls.admin_user, Role.ADMIN)

        cls.teacher_user = _create_user('class_teacher')
        _assign_role(cls.teacher_user, Role.TEACHER)

        cls.school = School.objects.create(
            name='Enroll School', slug='enroll-school', admin=cls.admin_user,
        )
        cls.department = Department.objects.create(
            school=cls.school, name='Gen Dept', slug='gen-dept',
        )
        cls.classroom = ClassRoom.objects.create(
            name='Year 3 Maths',
            school=cls.school,
            department=cls.department,
            created_by=cls.teacher_user,
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher_user)

    # -- tests ---------------------------------------------------------------

    def test_register_school_student(self):
        """POST to register_school_student creates a user with the student role."""
        client = Client()
        url = reverse('register_school_student')
        data = {
            'first_name': 'Tom',
            'last_name': 'Student',
            'email': 'tom.student@example.com',
            'username': 'tom_student',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
        }
        response = client.post(url, data)

        # Registration redirects to student_join_class
        self.assertEqual(response.status_code, 302)
        user = CustomUser.objects.get(username='tom_student')
        self.assertTrue(user.has_role(Role.STUDENT))
        self.assertEqual(user.first_name, 'Tom')

    def test_student_joins_class_by_code(self):
        """POST to student_join_class with a valid class code creates a pending enrollment."""
        from classroom.models import Enrollment

        student = _create_user('joiner_student', first_name='Jo', last_name='Iner')
        _assign_role(student, Role.STUDENT)

        client = Client()
        client.force_login(student)

        url = reverse('student_join_class')
        response = client.post(url, {'code': self.classroom.code})

        # Successful enrollment redirects to student_my_classes
        self.assertEqual(response.status_code, 302)
        enrollment = Enrollment.objects.get(classroom=self.classroom, student=student)
        self.assertEqual(enrollment.status, 'pending')

    def test_student_appears_in_class(self):
        """A ClassStudent entry makes the student visible in the classroom's students."""
        student = _create_user('visible_student')
        _assign_role(student, Role.STUDENT)

        ClassStudent.objects.create(classroom=self.classroom, student=student)

        self.assertIn(student, self.classroom.students.all())

    def test_student_enrollment_pending_approval(self):
        """A newly created Enrollment defaults to 'pending' status."""
        from classroom.models import Enrollment

        student = _create_user('pending_student')
        _assign_role(student, Role.STUDENT)

        enrollment = Enrollment.objects.create(
            classroom=self.classroom, student=student,
        )
        self.assertEqual(enrollment.status, 'pending')


# ---------------------------------------------------------------------------
# 5. ClassRoomSetupTest
# ---------------------------------------------------------------------------

class ClassRoomSetupTest(TestCase):
    """Test creating classrooms, assigning teachers, code uniqueness, and level mapping."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = _create_user('class_admin')
        _assign_role(cls.admin_user, Role.ADMIN)

        cls.teacher_user = _create_user('classroom_teacher')
        _assign_role(cls.teacher_user, Role.TEACHER)

        cls.school = School.objects.create(
            name='Classroom School', slug='classroom-school', admin=cls.admin_user,
        )
        cls.department = Department.objects.create(
            school=cls.school, name='Main Dept', slug='main-dept',
        )
        cls.subject = Subject.objects.create(
            name='English', slug='english', is_active=True,
        )
        cls.level1 = Level.objects.create(level_number=1, display_name='Year 1')
        cls.level2 = Level.objects.create(level_number=2, display_name='Year 2')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    # -- tests ---------------------------------------------------------------

    def test_create_class_with_level(self):
        """A ClassRoom can be created and linked to one or more levels."""
        classroom = ClassRoom.objects.create(
            name='Year 1 English',
            school=self.school,
            department=self.department,
            subject=self.subject,
            created_by=self.admin_user,
        )
        classroom.levels.add(self.level1)
        classroom.save()

        self.assertIn(self.level1, classroom.levels.all())
        self.assertEqual(classroom.school, self.school)
        self.assertEqual(classroom.department, self.department)

    def test_assign_teacher_to_class(self):
        """ClassTeacher links a teacher to a classroom."""
        classroom = ClassRoom.objects.create(
            name='Year 2 English',
            school=self.school,
            department=self.department,
            created_by=self.admin_user,
        )
        ct = ClassTeacher.objects.create(
            classroom=classroom, teacher=self.teacher_user,
        )
        self.assertEqual(ct.classroom, classroom)
        self.assertEqual(ct.teacher, self.teacher_user)
        self.assertIn(self.teacher_user, classroom.teachers.all())

    def test_class_code_is_unique(self):
        """Each ClassRoom automatically receives a unique 8-char code."""
        c1 = ClassRoom.objects.create(
            name='Class A', school=self.school, created_by=self.admin_user,
        )
        c2 = ClassRoom.objects.create(
            name='Class B', school=self.school, created_by=self.admin_user,
        )
        self.assertTrue(c1.code)
        self.assertTrue(c2.code)
        self.assertEqual(len(c1.code), 8)
        self.assertNotEqual(c1.code, c2.code)

    def test_map_levels_to_department(self):
        """DepartmentLevel M2M maps global Year levels to a department."""
        dl1 = DepartmentLevel.objects.create(
            department=self.department, level=self.level1, order=0,
        )
        dl2 = DepartmentLevel.objects.create(
            department=self.department, level=self.level2, order=1,
        )
        mapped = list(self.department.mapped_levels.order_by('level_number'))
        self.assertEqual(mapped, [self.level1, self.level2])
        self.assertEqual(dl1.effective_display_name, 'Year 1')
        self.assertEqual(dl2.effective_display_name, 'Year 2')
