"""
End-to-end / integration tests for features added to the CWA School App:

1. HoI upcoming classes on the HoDOverviewView dashboard (sessions only, no fallback).
2. Student upcoming classes on SubjectsHubView (sessions only, no fallback).
3. Department level linking via DepartmentSubjectLevelsView (link_level POST action).
4. CSV import global level mapping via execute_import() (global_level_map in structure_mapping).
"""

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject, DepartmentTeacher,
    Subject, Level, DepartmentLevel, ClassRoom, ClassTeacher, ClassStudent,
    SchoolStudent,
)


# ---------------------------------------------------------------------------
# Shared helpers (mirrors the pattern used in test_e2e_school_setup.py)
# ---------------------------------------------------------------------------

def _create_role(name, display_name=None):
    """Helper: get-or-create a Role row."""
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='password1!', **kwargs):
    """Helper: create a CustomUser."""
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'wlhtestmails+{username}@gmail.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    """Helper: assign a role to a user."""
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


# ---------------------------------------------------------------------------
# Feature 1: HoI upcoming classes (HoDOverviewView schedule fallback)
# ---------------------------------------------------------------------------

class HoIUpcomingClassesTest(TestCase):
    """
    The HoI dashboard shows upcoming sessions from ClassSession records only.
    The ClassRoom.day schedule fallback has been removed — next_classes_from_schedule
    is always empty; only real sessions appear in upcoming_sessions.
    """

    @classmethod
    def setUpTestData(cls):
        # Create an HoI user. Saving a School with an admin automatically
        # creates a SchoolTeacher(role='head_of_institute') and assigns the
        # HEAD_OF_INSTITUTE role — so we don't need to do it manually.
        cls.hoi_user = _create_user(
            'hoi_upcoming', first_name='Head', last_name='Teacher',
        )

        cls.school = School.objects.create(
            name='Upcoming School', slug='upcoming-school', admin=cls.hoi_user,
        )
        cls.department = Department.objects.create(
            school=cls.school, name='Math Dept', slug='math-dept',
        )
        # Classroom scheduled for Monday at 09:00 — no ClassSession rows exist.
        cls.classroom = ClassRoom.objects.create(
            name='Year 3 Maths',
            school=cls.school,
            department=cls.department,
            created_by=cls.hoi_user,
            day='monday',
            start_time='09:00',
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.hoi_user)

    # -- tests ---------------------------------------------------------------

    def test_hod_overview_returns_200(self):
        """GET /dashboard/ returns HTTP 200 for an HoI user."""
        url = reverse('hod_overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_hoi_schedule_fallback_removed(self):
        """
        The ClassRoom.day schedule fallback is gone — next_classes_from_schedule
        is always empty when no ClassSession records exist.
        """
        url = reverse('hod_overview')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        next_classes = response.context.get('next_classes_from_schedule', [])
        self.assertEqual(
            len(next_classes),
            0,
            'next_classes_from_schedule should be empty; schedule fallback was removed.',
        )

    def test_hoi_upcoming_sessions_from_classsession(self):
        """
        A real ClassSession record appears in upcoming_sessions on the HoI dashboard.
        """
        from datetime import date, time, timedelta
        from classroom.models import ClassSession

        future_date = date.today() + timedelta(days=2)
        session = ClassSession.objects.create(
            classroom=self.classroom,
            date=future_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            status='scheduled',
            created_by=self.hoi_user,
        )

        url = reverse('hod_overview')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        upcoming = response.context.get('upcoming_sessions', [])
        session_ids = [s.id for s in upcoming]
        self.assertIn(
            session.id,
            session_ids,
            'The ClassSession should appear in upcoming_sessions.',
        )

    def test_hoi_not_assigned_as_class_teacher(self):
        """
        Verify the test fixture is correct: the HoI is NOT a ClassTeacher for
        the classroom, so the view must use the HoI-school-scope fallback path.
        """
        is_class_teacher = ClassTeacher.objects.filter(
            classroom=self.classroom, teacher=self.hoi_user,
        ).exists()
        self.assertFalse(is_class_teacher)


# ---------------------------------------------------------------------------
# Feature 2: Student upcoming classes fallback (SubjectsHubView)
# ---------------------------------------------------------------------------

class StudentUpcomingClassesFallbackTest(TestCase):
    """
    The student hub (/hub/) populates 'upcoming_classes' from ClassSession
    records only. The ClassRoom.day schedule fallback has been removed —
    upcoming_classes is empty when no ClassSession records exist.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = _create_user('hub_admin', first_name='Admin', last_name='User')
        _assign_role(cls.admin_user, Role.ADMIN)

        cls.student_user = _create_user(
            'hub_student', first_name='Sam', last_name='Student',
        )
        _assign_role(cls.student_user, Role.STUDENT)

        cls.school = School.objects.create(
            name='Hub Test School', slug='hub-test-school', admin=cls.admin_user,
        )
        cls.department = Department.objects.create(
            school=cls.school, name='Science Dept', slug='science-dept',
        )
        # Classroom with a day schedule; no ClassSession rows.
        cls.classroom = ClassRoom.objects.create(
            name='Year 4 Science',
            school=cls.school,
            department=cls.department,
            created_by=cls.admin_user,
            day='wednesday',
            start_time='10:30',
        )
        # Enroll the student directly via ClassStudent (active enrollment).
        ClassStudent.objects.create(
            classroom=cls.classroom,
            student=cls.student_user,
            is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.student_user)

    # -- tests ---------------------------------------------------------------

    def test_subjects_hub_returns_200(self):
        """GET /hub/ returns HTTP 200 for a logged-in student."""
        url = reverse('subjects_hub')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_upcoming_classes_empty_without_sessions(self):
        """
        With no ClassSession records, upcoming_classes is empty.
        The ClassRoom.day schedule fallback has been removed.
        """
        url = reverse('subjects_hub')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        upcoming = response.context.get('upcoming_classes', [])
        self.assertEqual(
            len(upcoming),
            0,
            'upcoming_classes should be empty when no ClassSession records exist.',
        )

    def test_upcoming_classes_shows_real_session(self):
        """
        A ClassSession record for the enrolled classroom appears in upcoming_classes.
        """
        from datetime import date, time, timedelta
        from classroom.models import ClassSession

        future_date = date.today() + timedelta(days=2)
        session = ClassSession.objects.create(
            classroom=self.classroom,
            date=future_date,
            start_time=time(10, 30),
            end_time=time(11, 30),
            status='scheduled',
            created_by=self.admin_user,
        )

        url = reverse('subjects_hub')
        response = self.client.get(url)

        upcoming = response.context.get('upcoming_classes', [])
        classroom_ids = [entry.classroom.id for entry in upcoming]
        self.assertIn(
            self.classroom.id,
            classroom_ids,
            'The enrolled classroom should appear in upcoming_classes via ClassSession.',
        )
        session.delete()

    def test_student_is_enrolled_in_classroom(self):
        """Sanity-check: student has an active ClassStudent entry."""
        self.assertIn(self.student_user, self.classroom.students.all())


# ---------------------------------------------------------------------------
# Feature 3: Department level linking (DepartmentSubjectLevelsView)
# ---------------------------------------------------------------------------

class DepartmentLevelLinkingTest(TestCase):
    """
    An HoI can link a global Level to a department via a POST to
    admin_department_subject_levels with action='link_level'.
    """

    @classmethod
    def setUpTestData(cls):
        cls.hoi_user = _create_user(
            'dept_hoi', first_name='Institute', last_name='Head',
        )
        # Creating a School with admin= automatically grants HoI role.
        cls.school = School.objects.create(
            name='Level Link School', slug='level-link-school', admin=cls.hoi_user,
        )
        cls.department = Department.objects.create(
            school=cls.school, name='English Dept', slug='english-dept',
        )
        cls.subject = Subject.objects.create(
            name='English', slug='english', is_active=True,
        )
        # Link the subject to the department so the view can resolve it.
        DepartmentSubject.objects.create(
            department=cls.department, subject=cls.subject, order=0,
        )
        # Global level (school=None means it is a system-wide level).
        cls.global_level = Level.objects.create(
            level_number=4,
            display_name='Year 4',
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.hoi_user)

    # -- tests ---------------------------------------------------------------

    def test_link_level_creates_department_level(self):
        """
        POSTing action='link_level' with a valid global_level_id should create
        a DepartmentLevel linking the department to the global level.
        """
        url = reverse(
            'admin_department_subject_levels',
            kwargs={'school_id': self.school.id, 'dept_id': self.department.id},
        )
        data = {
            'action': 'link_level',
            'global_level_id': str(self.global_level.id),
            'subject_id': str(self.subject.id),
        }
        response = self.client.post(url, data)

        # The view redirects back to the same page on success.
        self.assertRedirects(
            response,
            reverse(
                'admin_department_subject_levels',
                kwargs={'school_id': self.school.id, 'dept_id': self.department.id},
            ),
        )
        # The DepartmentLevel through-table entry must now exist.
        self.assertTrue(
            DepartmentLevel.objects.filter(
                department=self.department,
                level=self.global_level,
            ).exists(),
            'DepartmentLevel should have been created by the link_level action.',
        )

    def test_link_level_redirects_back_to_page(self):
        """The POST response is a redirect (302) to the subject-levels page."""
        url = reverse(
            'admin_department_subject_levels',
            kwargs={'school_id': self.school.id, 'dept_id': self.department.id},
        )
        response = self.client.post(url, {
            'action': 'link_level',
            'global_level_id': str(self.global_level.id),
        })
        self.assertEqual(response.status_code, 302)

    def test_link_invalid_level_does_not_create_department_level(self):
        """
        POSTing link_level with a non-existent global_level_id must not
        create any DepartmentLevel row and should still redirect.
        """
        url = reverse(
            'admin_department_subject_levels',
            kwargs={'school_id': self.school.id, 'dept_id': self.department.id},
        )
        initial_count = DepartmentLevel.objects.filter(department=self.department).count()
        response = self.client.post(url, {
            'action': 'link_level',
            'global_level_id': '999999',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            DepartmentLevel.objects.filter(department=self.department).count(),
            initial_count,
            'No DepartmentLevel should be created for a non-existent global level.',
        )

    def test_get_subject_levels_page_returns_200(self):
        """GET on the subject-levels page returns HTTP 200."""
        url = reverse(
            'admin_department_subject_levels',
            kwargs={'school_id': self.school.id, 'dept_id': self.department.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Feature 4: CSV import global level mapping (execute_import)
# ---------------------------------------------------------------------------

class CSVImportGlobalLevelMappingTest(TestCase):
    """
    execute_import() should add global levels to classrooms when the
    structure_mapping contains a global_level_map entry.
    """

    @classmethod
    def setUpTestData(cls):
        cls.hoi_user = _create_user(
            'csv_hoi', first_name='CSV', last_name='Importer',
        )
        cls.school = School.objects.create(
            name='CSV Import School', slug='csv-import-school', admin=cls.hoi_user,
        )
        cls.department = Department.objects.create(
            school=cls.school,
            name='Maths Dept',
            slug='maths-dept',
            head=cls.hoi_user,
        )
        # Global level (school=None) to be mapped via global_level_map.
        cls.global_level = Level.objects.create(
            level_number=3,
            display_name='Year 3',
        )
        # Local / school-specific level that will be the primary level_map target.
        cls.local_level = Level.objects.create(
            level_number=203,
            display_name='Grade 3',
            school=cls.school,
        )

    # -- tests ---------------------------------------------------------------

    def test_execute_import_adds_global_level_to_classroom(self):
        """
        When global_level_map maps a CSV level name to a global Level id,
        the created classroom should have that global level in its levels M2M.
        """
        from classroom.import_services import execute_import

        preview_data = {
            'structure_mapping': {
                'department_id': self.department.id,
                'subject_map': {
                    'Grade 3 Maths': 'create',
                },
                'level_map': {
                    'Grade 3': str(self.local_level.id),
                },
                # Link the CSV level name to the global Year 3 level.
                'global_level_map': {
                    'Grade 3': self.global_level.id,
                },
                'class_map': {
                    'Grade 3 Class A': 'create',
                },
                'teacher_map': {},
            },
            'students_new': [],
            'students_existing': [],
            'guardians_new': [],
        }

        result = execute_import(
            preview_data=preview_data,
            school=self.school,
            uploaded_by=self.hoi_user,
        )

        # Exactly one class should have been created.
        self.assertEqual(result['counts']['classes_created'], 1)

        classroom = ClassRoom.objects.get(
            name='Grade 3 Class A', school=self.school,
        )
        classroom_level_ids = list(classroom.levels.values_list('id', flat=True))
        self.assertIn(
            self.global_level.id,
            classroom_level_ids,
            'The classroom should include the global level from global_level_map.',
        )

    def test_execute_import_creates_department_level_for_global_level(self):
        """
        execute_import should also create a DepartmentLevel record linking the
        department to the global level specified in global_level_map.
        """
        from classroom.import_services import execute_import

        preview_data = {
            'structure_mapping': {
                'department_id': self.department.id,
                'subject_map': {
                    'Year 3 English': 'create',
                },
                'level_map': {
                    'Grade 3': str(self.local_level.id),
                },
                'global_level_map': {
                    'Grade 3': self.global_level.id,
                },
                'class_map': {
                    'Year 3 English Class': 'create',
                },
                'teacher_map': {},
            },
            'students_new': [],
            'students_existing': [],
            'guardians_new': [],
        }

        execute_import(
            preview_data=preview_data,
            school=self.school,
            uploaded_by=self.hoi_user,
        )

        self.assertTrue(
            DepartmentLevel.objects.filter(
                department=self.department,
                level=self.global_level,
            ).exists(),
            'execute_import should create a DepartmentLevel for the global level.',
        )

    def test_execute_import_without_global_level_map_still_creates_class(self):
        """
        A structure_mapping without a global_level_map should still create the
        classroom correctly (regression guard).
        """
        from classroom.import_services import execute_import

        preview_data = {
            'structure_mapping': {
                'department_id': self.department.id,
                'subject_map': {
                    'Basic Maths': 'create',
                },
                'level_map': {
                    'Basic': str(self.local_level.id),
                },
                # No global_level_map key at all.
                'class_map': {
                    'Basic Maths Class': 'create',
                },
                'teacher_map': {},
            },
            'students_new': [],
            'students_existing': [],
            'guardians_new': [],
        }

        result = execute_import(
            preview_data=preview_data,
            school=self.school,
            uploaded_by=self.hoi_user,
        )

        self.assertEqual(result['counts']['classes_created'], 1)
        self.assertTrue(
            ClassRoom.objects.filter(name='Basic Maths Class', school=self.school).exists(),
        )
