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


def _create_user(username, password='password1!', **kwargs):
    """Create a CustomUser."""
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'wlhtestmails+{username}@gmail.com'),
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
        SchoolTeacher.objects.update_or_create(
            school=cls.school,
            teacher=cls.admin_user, defaults={'role': 'head_of_institute', 'is_active': True})
        SchoolTeacher.objects.update_or_create(
            school=cls.school,
            teacher=cls.teacher_user, defaults={'role': 'senior_teacher', 'is_active': True})

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
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=plain_teacher, defaults={'role': 'teacher', 'is_active': True})
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
            f'status_{self.student_user.id}_{self.criteria.id}': 'developing',
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
        self.assertEqual(record.status, 'developing')
        self.assertEqual(record.recorded_by, self.teacher_user)

    def test_record_progress_saves_and_updates_comment(self):
        """The record-progress form saves a per-student comment, and re-posting
        updates the same comment rather than creating a duplicate."""
        from classroom.models import ProgressReportComment
        self.client.force_login(self.teacher_user)
        sess = self.client.session
        sess['current_school_id'] = self.school.id
        sess.save()
        url = reverse('record_progress', kwargs={'class_id': self.classroom.id})

        self.client.post(url, {f'comment_{self.student_user.id}': 'Great improvement!'})
        c = ProgressReportComment.objects.get(student=self.student_user)
        self.assertEqual(c.body, 'Great improvement!')
        self.assertEqual(c.subject, self.classroom.subject)
        self.assertEqual(c.created_by, self.teacher_user)

        self.client.post(url, {f'comment_{self.student_user.id}': 'Even better now.'})
        self.assertEqual(
            ProgressReportComment.objects.filter(student=self.student_user).count(), 1,
        )
        c.refresh_from_db()
        self.assertEqual(c.body, 'Even better now.')

    def test_record_progress_prefills_existing_comment(self):
        """The form GET prefills each student's latest subject comment."""
        from classroom.models import ProgressReportComment
        ProgressReportComment.objects.create(
            student=self.student_user, school=self.school,
            subject=self.classroom.subject, body='Prior note.',
            created_by=self.teacher_user,
        )
        self.client.force_login(self.teacher_user)
        sess = self.client.session
        sess['current_school_id'] = self.school.id
        sess.save()
        resp = self.client.get(
            reverse('record_progress', kwargs={'class_id': self.classroom.id}),
        )
        rows = {r['student'].id: r for r in resp.context['student_rows']}
        self.assertEqual(rows[self.student_user.id]['comment'], 'Prior note.')

    def test_student_can_view_own_progress(self):
        """A student can view their own progress page."""
        # Seed a progress record
        ProgressRecord.objects.create(
            student=self.student_user,
            criteria=self.criteria,
            status='advanced',
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
            f'progress_{self.student_user.id}_{self.criteria.id}': 'advanced',
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
        self.assertEqual(record.status, 'advanced')
        self.assertEqual(record.recorded_by, self.teacher_user)


# ---------------------------------------------------------------------------
# 6. AllSubjectsCriteriaTest  (subject = null  →  applies to all subjects)
# ---------------------------------------------------------------------------

class AllSubjectsCriteriaTest(_BaseAttendanceProgressTest):
    """Subject-agnostic criteria (subject=None): creation + surfacing everywhere.

    See SPEC_TEACHER_CLASS_STUDENT_PROGRESS §12.6.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # A second, UNRELATED subject + classroom (Coding) at the same school,
        # so we can prove an All-Subjects criterion surfaces regardless of subject.
        cls.coding_subject = Subject.objects.create(
            name='Coding', slug='coding', is_active=True,
        )
        DepartmentSubject.objects.create(
            department=cls.department, subject=cls.coding_subject,
        )
        cls.coding_level = Level.objects.create(
            level_number=2, display_name='Beginner', subject=cls.coding_subject,
        )
        cls.coding_class = _create_classroom(
            cls.school, cls.department, cls.coding_subject, 'Coding 101',
        )
        cls.coding_class.levels.add(cls.coding_level)
        ClassTeacher.objects.create(classroom=cls.coding_class, teacher=cls.teacher_user)
        ClassStudent.objects.create(
            classroom=cls.coding_class, student=cls.student_user, is_active=True,
        )

    def _login_teacher(self):
        self.client.force_login(self.teacher_user)
        session = self.client.session
        session['current_school_id'] = self.school.id
        session.save()

    def test_create_all_subjects_criteria(self):
        """POST with subject='all' creates a criterion with subject=None (and no level)."""
        self._login_teacher()
        self.client.post(reverse('progress_criteria_list'), {
            'name': 'Attendance & participation',
            'subject': 'all',
            'level': '',
            'order': '0',
        })
        criteria = ProgressCriteria.objects.get(name='Attendance & participation')
        self.assertIsNone(criteria.subject, 'subject=all should persist as NULL')
        self.assertIsNone(criteria.level)
        self.assertEqual(criteria.school, self.school)

    def test_all_subjects_criteria_recordable_for_unrelated_subject(self):
        """An approved subject=None criterion can be recorded against a class of ANY subject."""
        all_subj = ProgressCriteria.objects.create(
            school=self.school, subject=None, level=None,
            name='Homework completed on time', status='approved',
            created_by=self.teacher_user, approved_by=self.teacher_user,
        )
        self._login_teacher()
        # Record it against the Coding class — different from the criterion's (null) subject.
        self.client.post(
            reverse('record_progress', kwargs={'class_id': self.coding_class.id}),
            {f'status_{self.student_user.id}_{all_subj.id}': 'advanced'},
        )
        self.assertTrue(
            ProgressRecord.objects.filter(
                student=self.student_user, criteria=all_subj,
            ).exists(),
            'All-Subjects criterion should be recordable for a class of any subject',
        )

    def test_all_subjects_criteria_in_record_progress_context(self):
        """GET record-progress lists the All-Subjects criterion alongside subject-specific ones."""
        all_subj = ProgressCriteria.objects.create(
            school=self.school, subject=None, level=None,
            name='Class behaviour', status='approved',
            created_by=self.teacher_user, approved_by=self.teacher_user,
        )
        self._login_teacher()
        resp = self.client.get(
            reverse('record_progress', kwargs={'class_id': self.classroom.id}),
        )
        self.assertEqual(resp.status_code, 200)
        listed_ids = [h['criteria'].id for h in resp.context['hierarchical_criteria']]
        self.assertIn(all_subj.id, listed_ids)

    def test_all_subjects_criteria_str_is_null_safe(self):
        """__str__ renders 'All Subjects' / 'All Levels' rather than crashing on null."""
        crit = ProgressCriteria.objects.create(
            school=self.school, subject=None, level=None, name='Curiosity',
        )
        self.assertIn('All Subjects', str(crit))
        self.assertIn('All Levels', str(crit))


# ---------------------------------------------------------------------------
# 7. RubricRatingTest  (4-level rating scale — §12.7)
# ---------------------------------------------------------------------------

class RubricRatingTest(_BaseAttendanceProgressTest):
    """The Beginning/Developing/Confident/Advanced rubric + proficiency buckets."""

    def _approved_criterion(self, name, order=0):
        return ProgressCriteria.objects.create(
            school=self.school, subject=self.subject, level=self.level,
            name=name, order=order, status='approved',
            created_by=self.teacher_user, approved_by=self.teacher_user,
        )

    def test_is_proficient_property(self):
        crit = self._approved_criterion('Crit')
        cases = {
            'not_started': False, 'beginning': False, 'developing': False,
            'confident': True, 'advanced': True,
        }
        for status, expected in cases.items():
            rec = ProgressRecord.objects.create(
                student=self.student_user, criteria=crit, status=status,
                recorded_by=self.teacher_user,
            )
            self.assertEqual(rec.is_proficient, expected, status)
            rec.delete()

    def test_record_progress_accepts_rubric_status(self):
        """The record-progress view stores a 4-level rubric value."""
        crit = self._approved_criterion('Solves problems')
        self.client.force_login(self.teacher_user)
        s = self.client.session
        s['current_school_id'] = self.school.id
        s.save()
        self.client.post(
            reverse('record_progress', kwargs={'class_id': self.classroom.id}),
            {f'status_{self.student_user.id}_{crit.id}': 'confident'},
        )
        rec = ProgressRecord.objects.get(student=self.student_user, criteria=crit)
        self.assertEqual(rec.status, 'confident')

    def test_summary_buckets(self):
        """overall.achieved = proficient (Confident+Advanced); in_progress = developing."""
        c1 = self._approved_criterion('A', 1)
        c2 = self._approved_criterion('B', 2)
        c3 = self._approved_criterion('C', 3)
        c4 = self._approved_criterion('D', 4)
        for crit, status in [(c1, 'advanced'), (c2, 'confident'),
                             (c3, 'developing'), (c4, 'not_started')]:
            ProgressRecord.objects.create(
                student=self.student_user, criteria=crit, status=status,
                recorded_by=self.teacher_user,
            )
        self.client.force_login(self.teacher_user)
        s = self.client.session
        s['current_school_id'] = self.school.id
        s.save()
        resp = self.client.get(
            reverse('student_progress', kwargs={'student_id': self.student_user.id}),
        )
        overall = resp.context['overall']
        self.assertEqual(overall['achieved'], 2)      # advanced + confident
        self.assertEqual(overall['in_progress'], 1)   # developing
        self.assertEqual(overall['not_started'], 1)

    def test_records_grouped_under_parent_criteria(self):
        """In a report group, each sub-criterion follows its parent (is_child)."""
        from classroom.views_progress import _build_student_progress

        def crit(name, order, parent=None):
            return ProgressCriteria.objects.create(
                school=self.school, subject=self.subject, level=self.level,
                name=name, order=order, parent=parent, status='approved',
                created_by=self.teacher_user, approved_by=self.teacher_user,
            )
        focus = crit('Focus', 0)
        c1 = crit('Pays attention', 0, parent=focus)
        c2 = crit('Stays on task', 1, parent=focus)
        solving = crit('Problem Solving', 1)
        for c in (focus, c1, c2, solving):
            ProgressRecord.objects.create(
                student=self.student_user, criteria=c, status='confident',
                recorded_by=self.teacher_user,
            )
        grouped, _ = _build_student_progress(self.student_user)
        recs = grouped[0]['records']
        self.assertEqual(
            [r.criteria.name for r in recs],
            ['Focus', 'Pays attention', 'Stays on task', 'Problem Solving'],
        )
        self.assertEqual([r.is_child for r in recs], [False, True, True, False])


# ---------------------------------------------------------------------------
# 8. ReportBuilderTest  (per-class report builder + dashboard card — §12.8)
# ---------------------------------------------------------------------------

class ReportBuilderTest(_BaseAttendanceProgressTest):
    """Per-class generation, section selection + snapshot, dashboard summary."""

    def _login_teacher(self):
        self.client.force_login(self.teacher_user)
        s = self.client.session
        s['current_school_id'] = self.school.id
        s.save()

    def test_class_builder_get_lists_students(self):
        self._login_teacher()
        resp = self.client.get(
            reverse('progress_report_class_builder', kwargs={'class_id': self.classroom.id}),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.student_user, list(resp.context['students']))

    def test_class_builder_generates_report_per_student_with_sections(self):
        from classroom.models import ProgressReport
        self._login_teacher()
        self.client.post(
            reverse('progress_report_class_builder', kwargs={'class_id': self.classroom.id}),
            {'include_rubric': 'on', 'include_homework': 'on'},
        )
        report = ProgressReport.objects.get(student=self.student_user, school=self.school)
        self.assertEqual(report.classroom, self.classroom)
        self.assertTrue(report.include_rubric)
        self.assertTrue(report.include_homework)
        self.assertFalse(report.include_maths)
        # Homework section was ticked → snapshot carries the homework summary.
        self.assertIn('homework', report.summary_snapshot)
        self.assertNotIn('maths', report.summary_snapshot)

    def test_per_student_generate_persists_selection(self):
        from classroom.models import ProgressReport
        self._login_teacher()
        self.client.post(
            reverse('progress_report_generate', kwargs={'student_id': self.student_user.id}),
            {'include_rubric': 'on', 'include_maths': 'on',
             'classroom': self.classroom.id},
        )
        report = ProgressReport.objects.get(student=self.student_user)
        self.assertTrue(report.include_maths)
        self.assertFalse(report.include_homework)
        self.assertIn('maths', report.summary_snapshot)

    def test_dashboard_shows_report_summary(self):
        from classroom.models import ProgressReport
        ProgressReport.objects.create(
            student=self.student_user, school=self.school,
            classroom=self.classroom, include_rubric=True,
            include_homework=True,
            summary_snapshot={'homework': {'assigned': 0, 'completed': 0,
                                           'completion_pct': 0, 'average_pct': 0}},
            generated_by=self.teacher_user,
        )
        self.client.force_login(self.student_user)
        s = self.client.session
        s['current_school_id'] = self.school.id
        s.save()
        resp = self.client.get(reverse('student_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'My Progress Summary')
        self.assertEqual(resp.context['progress_report'].include_homework, True)
