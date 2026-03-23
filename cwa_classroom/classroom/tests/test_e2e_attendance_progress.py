"""
End-to-end tests for the attendance marking and progress recording flows.

Covers:
  - Session scheduling (start-session, create-session)
  - Student attendance marking (present/absent/bulk)
  - Teacher self-attendance
  - Progress criteria CRUD and approval workflow
  - Progress recording and student progress viewing
"""

import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, ModuleSubscription
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject,
    Subject, Level, DepartmentLevel, ClassRoom, ClassTeacher,
    ClassStudent, SchoolStudent, ProgressCriteria, ProgressRecord,
    ClassSession, StudentAttendance, TeacherAttendance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name, display_name=None):
    """Get-or-create a Role row."""
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='testpass123', **kwargs):
    """Create a CustomUser."""
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'{username}@example.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    """Assign a role to a user."""
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school_with_subscription(admin_user, school_name='Test School'):
    """Create a school with an active subscription and all modules enabled."""
    school = School.objects.create(
        name=school_name,
        slug=school_name.lower().replace(' ', '-'),
        admin=admin_user,
        is_active=True,
    )
    plan = InstitutePlan.objects.create(
        name='Test Plan',
        slug='test-plan',
        price=Decimal('0.00'),
        class_limit=100,
        student_limit=100,
        invoice_limit_yearly=1000,
        extra_invoice_rate=Decimal('0.00'),
    )
    subscription = SchoolSubscription.objects.create(
        school=school,
        plan=plan,
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    # Enable all attendance/progress modules
    for module_code in (
        ModuleSubscription.MODULE_TEACHERS_ATTENDANCE,
        ModuleSubscription.MODULE_STUDENTS_ATTENDANCE,
        ModuleSubscription.MODULE_PROGRESS_REPORTS,
    ):
        ModuleSubscription.objects.create(
            school_subscription=subscription,
            module=module_code,
            is_active=True,
        )
    return school


def _create_classroom(school, department, subject, name='Test Class'):
    """Create a classroom within the given school/department."""
    classroom = ClassRoom(
        name=name,
        school=school,
        department=department,
        subject=subject,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
    )
    classroom.save()
    return classroom


class _BaseAttendanceProgressTest(TestCase):
    """
    Shared setUpTestData for all attendance and progress test classes.

    Creates:
      - admin_user (ADMIN + HEAD_OF_INSTITUTE)
      - teacher_user (SENIOR_TEACHER)
      - student_user (STUDENT)
      - A school with an active subscription and all modules enabled
      - A department, subject, level, DepartmentLevel
      - A classroom with teacher and student enrolled
      - SchoolTeacher records
    """

    @classmethod
    def setUpTestData(cls):
        # --- Users ---
        cls.admin_user = _create_user('admin_hoi', first_name='Admin', last_name='Owner')
        _assign_role(cls.admin_user, Role.ADMIN)
        _assign_role(cls.admin_user, Role.HEAD_OF_INSTITUTE)

        cls.teacher_user = _create_user('teacher_sr', first_name='Senior', last_name='Teacher')
        _assign_role(cls.teacher_user, Role.SENIOR_TEACHER)

        cls.student_user = _create_user('student_one', first_name='Alice', last_name='Student')
        _assign_role(cls.student_user, Role.STUDENT)

        # --- School + subscription ---
        cls.school = _setup_school_with_subscription(cls.admin_user, 'Attendance School')

        # --- Department ---
        cls.department = Department.objects.create(
            name='Maths Dept',
            school=cls.school,
            head=cls.admin_user,
            is_active=True,
        )

        # --- Subject ---
        cls.subject = Subject.objects.create(
            name='Mathematics',
            slug='mathematics',
            is_active=True,
        )
        DepartmentSubject.objects.create(department=cls.department, subject=cls.subject)

        # --- Level ---
        cls.level = Level.objects.create(
            level_number=1,
            display_name='Year 1',
            subject=cls.subject,
        )
        DepartmentLevel.objects.create(department=cls.department, level=cls.level)

        # --- Classroom ---
        cls.classroom = _create_classroom(cls.school, cls.department, cls.subject, 'Maths 101')
        cls.classroom.levels.add(cls.level)

        # --- SchoolTeacher memberships ---
        SchoolTeacher.objects.create(
            school=cls.school,
            teacher=cls.admin_user,
            role='head_of_institute',
            is_active=True,
        )
        SchoolTeacher.objects.create(
            school=cls.school,
            teacher=cls.teacher_user,
            role='senior_teacher',
            is_active=True,
        )

        # --- Assign teacher to classroom ---
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher_user)

        # --- Enroll student ---
        SchoolStudent.objects.create(school=cls.school, student=cls.student_user, is_active=True)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student_user, is_active=True)

    def setUp(self):
        self.client = Client()


# ---------------------------------------------------------------------------
# 1. SessionSchedulingTest
# ---------------------------------------------------------------------------

class SessionSchedulingTest(_BaseAttendanceProgressTest):
    """Test creating class sessions via start-session and create-session."""

    def test_schedule_session(self):
        """POST to start_session creates a session for today and redirects to attendance."""
        self.client.force_login(self.teacher_user)
        # Set school in session
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('start_session', kwargs={'class_id': self.classroom.id})
        response = self.client.post(url)

        # A session should have been created for today
        today = timezone.localdate()
        self.assertTrue(
            ClassSession.objects.filter(classroom=self.classroom, date=today).exists()
        )
        cs = ClassSession.objects.get(classroom=self.classroom, date=today)
        # Should redirect to session_attendance
        self.assertRedirects(
            response,
            reverse('session_attendance', kwargs={'session_id': cs.id}),
        )

    def test_session_created_with_correct_fields(self):
        """A session created via create_session has the expected date, times, and status."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('create_session', kwargs={'class_id': self.classroom.id})
        target_date = datetime.date(2026, 6, 15)
        data = {
            'date': target_date.isoformat(),
            'start_time': '09:00',
            'end_time': '10:00',
        }
        self.client.post(url, data)

        cs = ClassSession.objects.get(classroom=self.classroom, date=target_date)
        self.assertEqual(cs.status, 'scheduled')
        self.assertEqual(cs.start_time, datetime.time(9, 0))
        self.assertEqual(cs.end_time, datetime.time(10, 0))
        self.assertEqual(cs.created_by, self.teacher_user)


# ---------------------------------------------------------------------------
# 2. StudentAttendanceTest
# ---------------------------------------------------------------------------

class StudentAttendanceTest(_BaseAttendanceProgressTest):
    """Test marking student attendance via the session attendance form."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Pre-create a session for attendance tests
        cls.session = ClassSession.objects.create(
            classroom=cls.classroom,
            date=datetime.date(2026, 4, 1),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='scheduled',
            created_by=cls.teacher_user,
        )

    def test_mark_student_present(self):
        """POST with status_<id>=present records a present attendance."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('session_attendance', kwargs={'session_id': self.session.id})
        data = {f'status_{self.student_user.id}': 'present'}
        self.client.post(url, data)

        att = StudentAttendance.objects.get(session=self.session, student=self.student_user)
        self.assertEqual(att.status, 'present')
        self.assertEqual(att.marked_by, self.teacher_user)
        self.assertFalse(att.self_reported)

    def test_mark_student_absent(self):
        """POST with status_<id>=absent records an absent attendance."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('session_attendance', kwargs={'session_id': self.session.id})
        data = {f'status_{self.student_user.id}': 'absent'}
        self.client.post(url, data)

        att = StudentAttendance.objects.get(session=self.session, student=self.student_user)
        self.assertEqual(att.status, 'absent')

    def test_bulk_mark_attendance(self):
        """Multiple students can be marked in a single POST."""
        # Create a second student
        student2 = _create_user('student_two', first_name='Bob', last_name='Learner')
        _assign_role(student2, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student2, is_active=True)
        ClassStudent.objects.create(classroom=self.classroom, student=student2, is_active=True)

        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('session_attendance', kwargs={'session_id': self.session.id})
        data = {
            f'status_{self.student_user.id}': 'present',
            f'status_{student2.id}': 'absent',
        }
        self.client.post(url, data)

        att1 = StudentAttendance.objects.get(session=self.session, student=self.student_user)
        att2 = StudentAttendance.objects.get(session=self.session, student=student2)
        self.assertEqual(att1.status, 'present')
        self.assertEqual(att2.status, 'absent')

    def test_attendance_requires_teacher_role(self):
        """A user without a teacher role cannot access the session attendance page."""
        no_role_user = _create_user('norole_user')
        self.client.force_login(no_role_user)

        url = reverse('session_attendance', kwargs={'session_id': self.session.id})
        response = self.client.get(url)

        # RoleRequiredMixin redirects users without the required role
        self.assertNotEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# 3. TeacherAttendanceTest
# ---------------------------------------------------------------------------

class TeacherAttendanceTest(_BaseAttendanceProgressTest):
    """Test teacher self-attendance recording."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.session = ClassSession.objects.create(
            classroom=cls.classroom,
            date=datetime.date(2026, 4, 2),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='scheduled',
            created_by=cls.teacher_user,
        )

    def test_teacher_marks_own_attendance(self):
        """POST to teacher_self_attendance records a TeacherAttendance row."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('teacher_self_attendance', kwargs={'session_id': self.session.id})
        data = {'status': 'present'}
        response = self.client.post(url, data)

        self.assertTrue(
            TeacherAttendance.objects.filter(
                session=self.session, teacher=self.teacher_user
            ).exists()
        )
        ta = TeacherAttendance.objects.get(session=self.session, teacher=self.teacher_user)
        self.assertEqual(ta.status, 'present')

    def test_teacher_attendance_recorded(self):
        """Teacher attendance is stored with self_reported=True for self-attendance."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('teacher_self_attendance', kwargs={'session_id': self.session.id})
        self.client.post(url, {'status': 'present'})

        ta = TeacherAttendance.objects.get(session=self.session, teacher=self.teacher_user)
        self.assertTrue(ta.self_reported)
        self.assertEqual(ta.teacher, self.teacher_user)


# ---------------------------------------------------------------------------
# 4. ProgressCriteriaTest
# ---------------------------------------------------------------------------

class ProgressCriteriaTest(_BaseAttendanceProgressTest):
    """Test creating, submitting, approving, and rejecting progress criteria."""

    def test_create_criteria(self):
        """POST to progress_criteria_list creates a ProgressCriteria for the school."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('progress_criteria_list')
        data = {
            'name': 'Count to 10',
            'description': 'Student can count aloud from 1 to 10.',
            'subject': self.subject.id,
            'level': self.level.id,
            'order': '1',
        }
        response = self.client.post(url, data)

        self.assertTrue(ProgressCriteria.objects.filter(name='Count to 10').exists())
        criteria = ProgressCriteria.objects.get(name='Count to 10')
        self.assertEqual(criteria.school, self.school)
        self.assertEqual(criteria.subject, self.subject)
        self.assertEqual(criteria.level, self.level)
        self.assertEqual(criteria.created_by, self.teacher_user)

    def test_criteria_requires_approval(self):
        """A TEACHER-role user creates criteria in draft status (needs approval)."""
        # Create a plain teacher (not senior)
        plain_teacher = _create_user('plain_teacher', first_name='Junior', last_name='T')
        _assign_role(plain_teacher, Role.TEACHER)
        SchoolTeacher.objects.create(
            school=self.school, teacher=plain_teacher, role='teacher', is_active=True,
        )
        ClassTeacher.objects.create(classroom=self.classroom, teacher=plain_teacher)

        self.client.force_login(plain_teacher)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('progress_criteria_list')
        data = {
            'name': 'Draft Criteria',
            'subject': self.subject.id,
            'level': self.level.id,
            'order': '0',
        }
        self.client.post(url, data)

        criteria = ProgressCriteria.objects.get(name='Draft Criteria')
        self.assertEqual(criteria.status, 'draft')
        self.assertIsNone(criteria.approved_by)

    def test_approve_criteria(self):
        """A SENIOR_TEACHER can approve a pending criteria."""
        # Create criteria in pending_approval state
        criteria = ProgressCriteria.objects.create(
            school=self.school,
            subject=self.subject,
            level=self.level,
            name='Pending Criteria',
            status='pending_approval',
            created_by=self.teacher_user,
        )

        self.client.force_login(self.teacher_user)  # senior teacher
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('progress_criteria_approve', kwargs={'criteria_id': criteria.id})
        self.client.post(url)

        criteria.refresh_from_db()
        self.assertEqual(criteria.status, 'approved')
        self.assertEqual(criteria.approved_by, self.teacher_user)

    def test_reject_criteria(self):
        """A SENIOR_TEACHER can reject a pending criteria."""
        criteria = ProgressCriteria.objects.create(
            school=self.school,
            subject=self.subject,
            level=self.level,
            name='To Be Rejected',
            status='pending_approval',
            created_by=self.teacher_user,
        )

        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('progress_criteria_reject', kwargs={'criteria_id': criteria.id})
        self.client.post(url)

        criteria.refresh_from_db()
        self.assertEqual(criteria.status, 'rejected')


# ---------------------------------------------------------------------------
# 5. ProgressRecordingTest
# ---------------------------------------------------------------------------

class ProgressRecordingTest(_BaseAttendanceProgressTest):
    """Test recording and viewing student progress."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Approved criteria required for progress recording
        cls.criteria = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject,
            level=cls.level,
            name='Addition Facts',
            status='approved',
            created_by=cls.teacher_user,
            approved_by=cls.teacher_user,
        )
        cls.session = ClassSession.objects.create(
            classroom=cls.classroom,
            date=datetime.date(2026, 4, 3),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='scheduled',
            created_by=cls.teacher_user,
        )

    def test_record_progress_for_student(self):
        """POST to record_progress creates a ProgressRecord for the student."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('record_progress', kwargs={'class_id': self.classroom.id})
        data = {
            f'status_{self.student_user.id}_{self.criteria.id}': 'in_progress',
        }
        self.client.post(url, data)

        self.assertTrue(
            ProgressRecord.objects.filter(
                student=self.student_user,
                criteria=self.criteria,
            ).exists()
        )
        record = ProgressRecord.objects.get(
            student=self.student_user, criteria=self.criteria,
        )
        self.assertEqual(record.status, 'in_progress')
        self.assertEqual(record.recorded_by, self.teacher_user)

    def test_student_can_view_own_progress(self):
        """A student can view their own progress page."""
        # Seed a progress record
        ProgressRecord.objects.create(
            student=self.student_user,
            criteria=self.criteria,
            status='achieved',
            recorded_by=self.teacher_user,
        )

        # Student needs STUDENT role to access the view
        self.client.force_login(self.student_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('student_progress', kwargs={'student_id': self.student_user.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    def test_progress_records_correct_status(self):
        """Recording progress via the session attendance form stores the right status values."""
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

        url = reverse('session_attendance', kwargs={'session_id': self.session.id})
        # Mark student attendance AND progress in a single POST
        data = {
            f'status_{self.student_user.id}': 'present',
            f'progress_{self.student_user.id}_{self.criteria.id}': 'achieved',
        }
        self.client.post(url, data)

        # Verify attendance was saved
        att = StudentAttendance.objects.get(
            session=self.session, student=self.student_user,
        )
        self.assertEqual(att.status, 'present')

        # Verify progress was saved with the session link
        record = ProgressRecord.objects.get(
            student=self.student_user,
            criteria=self.criteria,
            session=self.session,
        )
        self.assertEqual(record.status, 'achieved')
        self.assertEqual(record.recorded_by, self.teacher_user)
