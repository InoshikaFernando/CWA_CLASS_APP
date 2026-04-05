"""
Comprehensive view tests to increase coverage across:
- views_teacher.py, views_student.py, views_department.py,
- views_progress.py, views_salaries.py, views_email.py, views_invoicing.py
"""

import uuid
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, ModuleSubscription
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    ClassSession, Subject, Level, DepartmentLevel, DepartmentSubject,
    ClassStudent, ClassTeacher, Enrollment, StudentAttendance,
    TeacherAttendance, EmailCampaign, EmailLog, EmailPreference,
    ProgressCriteria, ProgressRecord, Notification,
    TeacherHourlyRate, TeacherRateOverride, SalarySlip, SalarySlipLineItem,
    Invoice, InvoiceLineItem, DepartmentFee, StudentFeeOverride,
    DepartmentTeacher,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='pass12345', **kwargs):
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'{username}@test.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _full_school_setup():
    """Create complete school with HoI, teacher, student, department, class."""
    hoi = _create_user('hoi', email='hoi@test.com')
    _assign_role(hoi, Role.HEAD_OF_INSTITUTE)

    teacher = _create_user('teacher1', email='t@test.com', first_name='John', last_name='Doe')
    _assign_role(teacher, Role.TEACHER)

    student = _create_user('student1', email='s@test.com', first_name='Jane', last_name='Smith')
    _assign_role(student, Role.STUDENT)

    school = School.objects.create(name='Test School', slug='test-school', admin=hoi)
    st, _ = SchoolTeacher.objects.update_or_create(school=school, teacher=teacher, defaults={'role': 'teacher'})
    SchoolStudent.objects.create(school=school, student=student)

    subject = Subject.objects.create(name='Maths', slug='maths')
    level = Level.objects.create(level_number=1, display_name='Level 1', subject=subject)
    dept = Department.objects.create(school=school, name='Mathematics', slug='mathematics')
    DepartmentSubject.objects.get_or_create(department=dept, subject=subject)
    DepartmentLevel.objects.get_or_create(department=dept, level=level)

    classroom = ClassRoom.objects.create(
        name='Class 1', school=school, subject=subject,
        department=dept, start_time=time(9, 0), end_time=time(10, 0),
    )
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)
    ClassStudent.objects.create(classroom=classroom, student=student)

    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{uuid.uuid4().hex[:6]}',
        price=Decimal('89.00'), stripe_price_id='price_test',
        class_limit=5, student_limit=100,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')

    return {
        'hoi': hoi, 'teacher': teacher, 'student': student,
        'school': school, 'dept': dept, 'classroom': classroom,
        'subject': subject, 'level': level, 'plan': plan, 'sub': sub,
        'school_teacher': st,
    }


def _enable_module(sub, module_name):
    """Create a ModuleSubscription for module-gated views."""
    return ModuleSubscription.objects.create(
        school_subscription=sub, module=module_name, is_active=True,
    )


# ===========================================================================
# TEACHER VIEWS
# ===========================================================================

class TeacherDashboardViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()

    def test_teacher_dashboard_get(self):
        self.client.login(username='teacher1', password='pass12345')
        resp = self.client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_teacher_dashboard_no_school(self):
        teacher2 = _create_user('teacher_no_school')
        _assign_role(teacher2, Role.TEACHER)
        self.client.login(username='teacher_no_school', password='pass12345')
        resp = self.client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_teacher_dashboard_unauthenticated_redirects(self):
        resp = self.client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 302)


class StartSessionViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')

    def test_start_session_creates_session(self):
        url = reverse('start_session', args=[self.data['classroom'].id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassSession.objects.filter(
                classroom=self.data['classroom'],
                date=timezone.localdate(),
            ).exists()
        )

    def test_start_session_existing_scheduled_redirects_to_attendance(self):
        session = ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='scheduled', created_by=self.data['teacher'],
        )
        url = reverse('start_session', args=[self.data['classroom'].id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/teacher/session/{session.id}/attendance/', resp.url)

    def test_start_session_completed_shows_info(self):
        ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='completed', created_by=self.data['teacher'],
        )
        url = reverse('start_session', args=[self.data['classroom'].id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

    def test_start_session_no_access(self):
        teacher2 = _create_user('teacher2')
        _assign_role(teacher2, Role.TEACHER)
        self.client.login(username='teacher2', password='pass12345')
        url = reverse('start_session', args=[self.data['classroom'].id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)


class CreateSessionViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')

    def test_create_session_get(self):
        url = reverse('create_session', args=[self.data['classroom'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_create_session_post_valid(self):
        url = reverse('create_session', args=[self.data['classroom'].id])
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(url, {
            'date': tomorrow,
            'start_time': '09:00',
            'end_time': '10:00',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassSession.objects.filter(
            classroom=self.data['classroom'],
        ).exists())

    def test_create_session_post_invalid_date(self):
        url = reverse('create_session', args=[self.data['classroom'].id])
        resp = self.client.post(url, {
            'date': 'not-a-date',
            'start_time': '09:00',
            'end_time': '10:00',
        })
        self.assertEqual(resp.status_code, 302)

    def test_create_session_post_duplicate(self):
        session_date = timezone.localdate() + timedelta(days=2)
        ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=session_date,
            start_time=time(9, 0), end_time=time(10, 0),
            status='scheduled', created_by=self.data['teacher'],
        )
        url = reverse('create_session', args=[self.data['classroom'].id])
        resp = self.client.post(url, {
            'date': session_date.isoformat(),
            'start_time': '09:00',
            'end_time': '10:00',
        })
        self.assertEqual(resp.status_code, 302)

    def test_create_session_no_access(self):
        teacher2 = _create_user('teacher_noaccess')
        _assign_role(teacher2, Role.TEACHER)
        self.client.login(username='teacher_noaccess', password='pass12345')
        url = reverse('create_session', args=[self.data['classroom'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_create_session_with_go_to_attendance(self):
        url = reverse('create_session', args=[self.data['classroom'].id])
        future = (timezone.localdate() + timedelta(days=5)).isoformat()
        resp = self.client.post(url, {
            'date': future,
            'start_time': '09:00',
            'end_time': '10:00',
            'go_to_attendance': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        session = ClassSession.objects.filter(classroom=self.data['classroom']).latest('id')
        self.assertIn(str(session.id), resp.url)


class CompleteSessionViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')
        self.session = ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='scheduled', created_by=self.data['teacher'],
        )

    def test_complete_session(self):
        url = reverse('complete_session', args=[self.session.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')

    def test_complete_already_completed(self):
        self.session.status = 'completed'
        self.session.save()
        url = reverse('complete_session', args=[self.session.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

    def test_complete_session_no_access(self):
        teacher2 = _create_user('teacher_complete_noaccess')
        _assign_role(teacher2, Role.TEACHER)
        self.client.login(username='teacher_complete_noaccess', password='pass12345')
        url = reverse('complete_session', args=[self.session.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)


class CancelSessionViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')
        self.session = ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='scheduled', created_by=self.data['teacher'],
        )

    def test_cancel_session(self):
        url = reverse('cancel_session', args=[self.session.id])
        resp = self.client.post(url, {'reason': 'Holiday'})
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'cancelled')
        self.assertEqual(self.session.cancellation_reason, 'Holiday')

    def test_cancel_completed_session(self):
        self.session.status = 'completed'
        self.session.save()
        url = reverse('cancel_session', args=[self.session.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')


class DeleteSessionViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')
        self.session = ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='scheduled', created_by=self.data['teacher'],
        )

    def test_delete_session(self):
        url = reverse('delete_session', args=[self.session.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ClassSession.objects.filter(id=self.session.id).exists())


class EnrollmentRequestsViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')
        Enrollment.objects.create(
            classroom=self.data['classroom'],
            student=self.data['student'],
            status='pending',
        )

    def test_enrollment_requests_get(self):
        resp = self.client.get(reverse('enrollment_requests'))
        self.assertEqual(resp.status_code, 200)

    def test_enrollment_approve(self):
        enrollment = Enrollment.objects.first()
        resp = self.client.post(reverse('enrollment_approve', args=[enrollment.id]))
        self.assertEqual(resp.status_code, 302)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, 'approved')

    def test_enrollment_requests_as_hoi(self):
        self.client.login(username='hoi', password='pass12345')
        resp = self.client.get(reverse('enrollment_requests'))
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# STUDENT VIEWS
# ===========================================================================

class JoinClassByCodeViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='student1', password='pass12345')

    def test_join_class_get(self):
        resp = self.client.get(reverse('student_join_class'))
        self.assertEqual(resp.status_code, 200)

    def test_join_class_empty_code(self):
        resp = self.client.post(reverse('student_join_class'), {'code': ''})
        self.assertEqual(resp.status_code, 200)

    def test_join_class_invalid_code(self):
        resp = self.client.post(reverse('student_join_class'), {'code': 'INVALID'})
        self.assertEqual(resp.status_code, 200)

    def test_join_class_already_enrolled(self):
        code = self.data['classroom'].code
        resp = self.client.post(reverse('student_join_class'), {'code': code})
        self.assertEqual(resp.status_code, 200)

    def test_join_class_new_enrollment(self):
        # Create a new classroom without this student
        classroom2 = ClassRoom.objects.create(
            name='Class 2', school=self.data['school'],
            subject=self.data['subject'],
        )
        resp = self.client.post(reverse('student_join_class'), {'code': classroom2.code})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Enrollment.objects.filter(
            classroom=classroom2, student=self.data['student'], status='pending',
        ).exists())

    def test_join_class_pending_enrollment_exists(self):
        classroom2 = ClassRoom.objects.create(
            name='Class 3', school=self.data['school'],
            subject=self.data['subject'],
        )
        Enrollment.objects.create(
            classroom=classroom2, student=self.data['student'], status='pending',
        )
        resp = self.client.post(reverse('student_join_class'), {'code': classroom2.code})
        self.assertEqual(resp.status_code, 200)

    def test_join_class_rejected_resubmit(self):
        classroom2 = ClassRoom.objects.create(
            name='Class 4', school=self.data['school'],
            subject=self.data['subject'],
        )
        Enrollment.objects.create(
            classroom=classroom2, student=self.data['student'], status='rejected',
        )
        resp = self.client.post(reverse('student_join_class'), {'code': classroom2.code})
        self.assertEqual(resp.status_code, 200)
        enrollment = Enrollment.objects.get(classroom=classroom2, student=self.data['student'])
        self.assertEqual(enrollment.status, 'pending')


# ===========================================================================
# ENROLLMENT NOTIFICATION LINK TESTS
# ===========================================================================

class EnrollmentRequestNotificationLinkTests(TestCase):
    """Teacher/HoD/HoI notifications must link to the enrollment-requests page."""

    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='student1', password='pass12345')

    def _join_new_class(self):
        """Create a fresh class and have student1 submit a join request."""
        classroom2 = ClassRoom.objects.create(
            name='Notify Class', school=self.data['school'],
            subject=self.data['subject'],
            department=self.data['dept'],
        )
        ClassTeacher.objects.create(classroom=classroom2, teacher=self.data['teacher'])
        self.client.post(reverse('student_join_class'), {'code': classroom2.code})
        return classroom2

    def test_teacher_notification_link_points_to_enrollment_requests(self):
        classroom2 = self._join_new_class()
        notif = Notification.objects.filter(
            user=self.data['teacher'],
            notification_type='enrollment_request',
        ).last()
        self.assertIsNotNone(notif, 'No enrollment_request notification created for teacher')
        self.assertEqual(notif.link, reverse('enrollment_requests'))

    def test_hod_notification_link_points_to_enrollment_requests(self):
        """HoD of the department gets a notification with the correct link."""
        # Make the hoi also a department head so we have an HoD
        hod = _create_user('hod_test', email='hod@test.com')
        _assign_role(hod, Role.HEAD_OF_DEPARTMENT)
        self.data['dept'].head = hod
        self.data['dept'].save()

        self._join_new_class()

        notif = Notification.objects.filter(
            user=hod,
            notification_type='enrollment_request',
        ).last()
        self.assertIsNotNone(notif, 'No enrollment_request notification created for HoD')
        self.assertEqual(notif.link, reverse('enrollment_requests'))

    def test_hoi_notification_link_points_to_enrollment_requests(self):
        """School admin (HoI) gets a notification with the correct link."""
        self._join_new_class()
        notif = Notification.objects.filter(
            user=self.data['hoi'],
            notification_type='enrollment_request',
        ).last()
        self.assertIsNotNone(notif, 'No enrollment_request notification created for HoI')
        self.assertEqual(notif.link, reverse('enrollment_requests'))

    def test_re_request_notification_link_also_correct(self):
        """Re-submitted join request also produces the correct link."""
        classroom2 = ClassRoom.objects.create(
            name='Re-request Class', school=self.data['school'],
            subject=self.data['subject'],
        )
        ClassTeacher.objects.create(classroom=classroom2, teacher=self.data['teacher'])
        # First rejection
        Enrollment.objects.create(
            classroom=classroom2, student=self.data['student'], status='rejected',
        )
        # Re-submit
        self.client.post(reverse('student_join_class'), {'code': classroom2.code})
        notif = Notification.objects.filter(
            user=self.data['teacher'],
            notification_type='enrollment_request',
        ).last()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.link, reverse('enrollment_requests'))


class EnrollmentApproveNotificationLinkTests(TestCase):
    """Student notification after approval must link to the class detail page."""

    def setUp(self):
        self.data = _full_school_setup()
        self.enrollment = Enrollment.objects.create(
            classroom=self.data['classroom'],
            student=self.data['student'],
            status='pending',
        )
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')

    def test_approval_creates_notification_with_class_detail_link(self):
        self.client.post(reverse('enrollment_approve', args=[self.enrollment.id]))
        notif = Notification.objects.filter(
            user=self.data['student'],
            notification_type='enrollment_approved',
        ).last()
        self.assertIsNotNone(notif, 'No enrollment_approved notification created')
        expected_link = reverse('student_class_detail', kwargs={'class_id': self.data['classroom'].id})
        self.assertEqual(notif.link, expected_link)

    def test_approval_notification_link_is_not_empty(self):
        self.client.post(reverse('enrollment_approve', args=[self.enrollment.id]))
        notif = Notification.objects.filter(
            user=self.data['student'],
            notification_type='enrollment_approved',
        ).last()
        self.assertTrue(notif.link, 'Approval notification link must not be empty')


class EnrollmentRejectNotificationLinkTests(TestCase):
    """Student notification after rejection must link to the join-class page."""

    def setUp(self):
        self.data = _full_school_setup()
        self.enrollment = Enrollment.objects.create(
            classroom=self.data['classroom'],
            student=self.data['student'],
            status='pending',
        )
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')

    def test_rejection_creates_notification_with_join_class_link(self):
        self.client.post(
            reverse('enrollment_reject', args=[self.enrollment.id]),
            {'rejection_reason': 'Class is full'},
        )
        notif = Notification.objects.filter(
            user=self.data['student'],
            notification_type='enrollment_rejected',
        ).last()
        self.assertIsNotNone(notif, 'No enrollment_rejected notification created')
        self.assertEqual(notif.link, reverse('student_join_class'))

    def test_rejection_notification_link_is_not_empty(self):
        self.client.post(
            reverse('enrollment_reject', args=[self.enrollment.id]),
            {'rejection_reason': ''},
        )
        notif = Notification.objects.filter(
            user=self.data['student'],
            notification_type='enrollment_rejected',
        ).last()
        self.assertTrue(notif.link, 'Rejection notification link must not be empty')

    def test_rejection_with_no_reason_still_has_correct_link(self):
        self.client.post(
            reverse('enrollment_reject', args=[self.enrollment.id]),
            {'rejection_reason': ''},
        )
        notif = Notification.objects.filter(
            user=self.data['student'],
            notification_type='enrollment_rejected',
        ).last()
        self.assertEqual(notif.link, reverse('student_join_class'))


class MyClassesViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='student1', password='pass12345')

    def test_my_classes_get(self):
        resp = self.client.get(reverse('student_my_classes'))
        self.assertEqual(resp.status_code, 200)


class StudentClassDetailViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='student1', password='pass12345')

    def test_class_detail_get(self):
        url = reverse('student_class_detail', args=[self.data['classroom'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_class_detail_not_enrolled(self):
        classroom2 = ClassRoom.objects.create(
            name='Other Class', school=self.data['school'],
            subject=self.data['subject'],
        )
        url = reverse('student_class_detail', args=[classroom2.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_class_detail_with_sessions_and_attendance(self):
        session = ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='completed', created_by=self.data['teacher'],
        )
        StudentAttendance.objects.create(
            session=session, student=self.data['student'],
            status='present', marked_by=self.data['teacher'],
        )
        url = reverse('student_class_detail', args=[self.data['classroom'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['present_count'], 1)


class StudentAttendanceHistoryViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_STUDENTS_ATTENDANCE)
        self.client = Client()
        self.client.login(username='student1', password='pass12345')

    def test_attendance_history_get(self):
        resp = self.client.get(reverse('student_attendance_history'))
        self.assertEqual(resp.status_code, 200)


class StudentSelfMarkAttendanceViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_STUDENTS_ATTENDANCE)
        self.client = Client()
        self.client.login(username='student1', password='pass12345')
        self.session = ClassSession.objects.create(
            classroom=self.data['classroom'],
            date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='completed', created_by=self.data['teacher'],
        )

    def test_self_mark_attendance_present(self):
        url = reverse('student_mark_attendance', args=[self.session.id])
        resp = self.client.post(url, {'status': 'present'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(StudentAttendance.objects.filter(
            session=self.session, student=self.data['student'],
            status='present', self_reported=True,
        ).exists())

    def test_self_mark_invalid_status(self):
        url = reverse('student_mark_attendance', args=[self.session.id])
        resp = self.client.post(url, {'status': 'absent'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StudentAttendance.objects.filter(
            session=self.session, student=self.data['student'],
        ).exists())

    def test_self_mark_not_enrolled(self):
        classroom2 = ClassRoom.objects.create(
            name='Other', school=self.data['school'], subject=self.data['subject'],
        )
        session2 = ClassSession.objects.create(
            classroom=classroom2, date=timezone.localdate(),
            start_time=time(9, 0), end_time=time(10, 0),
            status='completed', created_by=self.data['teacher'],
        )
        url = reverse('student_mark_attendance', args=[session2.id])
        resp = self.client.post(url, {'status': 'present'})
        self.assertEqual(resp.status_code, 302)

    def test_self_mark_session_not_completed(self):
        self.session.status = 'scheduled'
        self.session.save()
        url = reverse('student_mark_attendance', args=[self.session.id])
        resp = self.client.post(url, {'status': 'present'})
        self.assertEqual(resp.status_code, 302)

    def test_self_mark_already_marked_by_teacher(self):
        StudentAttendance.objects.create(
            session=self.session, student=self.data['student'],
            status='present', marked_by=self.data['teacher'], self_reported=False,
        )
        url = reverse('student_mark_attendance', args=[self.session.id])
        resp = self.client.post(url, {'status': 'present'})
        self.assertEqual(resp.status_code, 302)


class EnrollGlobalClassViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='student1', password='pass12345')
        self.global_class = ClassRoom.objects.create(
            name='Global Class', school=None,
            subject=self.data['subject'],
        )

    def test_enroll_global_class(self):
        url = reverse('student_enroll_global_class', args=[self.global_class.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassStudent.objects.filter(
            classroom=self.global_class, student=self.data['student'],
        ).exists())

    def test_enroll_global_class_already_enrolled(self):
        ClassStudent.objects.create(
            classroom=self.global_class, student=self.data['student'],
        )
        url = reverse('student_enroll_global_class', args=[self.global_class.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# DEPARTMENT VIEWS
# ===========================================================================

class DepartmentListViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_department_list_get(self):
        url = reverse('admin_school_departments', args=[self.data['school'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_departments'], 1)


class DepartmentCreateViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_create_department_get(self):
        url = reverse('admin_department_create', args=[self.data['school'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_create_department_post(self):
        url = reverse('admin_department_create', args=[self.data['school'].id])
        resp = self.client.post(url, {
            'name': 'Science',
            'description': 'Science Department',
            'subjects': [str(self.data['subject'].id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Department.objects.filter(
            school=self.data['school'], name='Science',
        ).exists())

    def test_create_department_empty_name(self):
        url = reverse('admin_department_create', args=[self.data['school'].id])
        resp = self.client.post(url, {'name': '', 'description': ''})
        self.assertEqual(resp.status_code, 200)

    def test_create_department_with_new_subject(self):
        url = reverse('admin_department_create', args=[self.data['school'].id])
        resp = self.client.post(url, {
            'name': 'Art',
            'description': 'Art Department',
            'new_subject_name': 'Visual Art',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(name='Visual Art').exists())


class DepartmentDetailViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_department_detail_get(self):
        url = reverse('admin_department_detail', args=[
            self.data['school'].id, self.data['dept'].id,
        ])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


class DepartmentEditViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_department_edit_get(self):
        url = reverse('admin_department_edit', args=[
            self.data['school'].id, self.data['dept'].id,
        ])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# EMAIL VIEWS
# ===========================================================================

class EmailDashboardViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_email_dashboard_get(self):
        resp = self.client.get(reverse('email_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_email_dashboard_no_school(self):
        user = _create_user('noadmin')
        _assign_role(user, Role.HEAD_OF_INSTITUTE)
        self.client.login(username='noadmin', password='pass12345')
        resp = self.client.get(reverse('email_dashboard'))
        self.assertEqual(resp.status_code, 302)


class EmailComposeViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_compose_get(self):
        resp = self.client.get(reverse('email_compose'))
        self.assertEqual(resp.status_code, 200)

    @patch('classroom.views_email.send_bulk_emails')
    def test_compose_post_send(self, mock_send):
        resp = self.client.post(reverse('email_compose'), {
            'name': 'Test Campaign',
            'subject': 'Hello Everyone',
            'html_body': '<p>Test body</p>',
            'action': 'send',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(EmailCampaign.objects.filter(name='Test Campaign').exists())
        mock_send.assert_called_once()

    def test_compose_post_draft(self):
        resp = self.client.post(reverse('email_compose'), {
            'name': 'Draft Campaign',
            'subject': 'Draft Subject',
            'html_body': '<p>Draft body</p>',
            'action': 'draft',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(EmailCampaign.objects.filter(name='Draft Campaign').exists())

    def test_compose_post_missing_fields(self):
        resp = self.client.post(reverse('email_compose'), {
            'name': '', 'subject': '', 'html_body': '',
        })
        self.assertEqual(resp.status_code, 302)

    def test_compose_post_with_roles_and_classes(self):
        with patch('classroom.views_email.send_bulk_emails'):
            resp = self.client.post(reverse('email_compose'), {
                'name': 'Targeted',
                'subject': 'For teachers',
                'html_body': '<p>Content</p>',
                'roles': ['teacher'],
                'class_ids': [str(self.data['classroom'].id)],
                'action': 'send',
            })
        self.assertEqual(resp.status_code, 302)
        campaign = EmailCampaign.objects.get(name='Targeted')
        self.assertIn('roles', campaign.recipient_filter)
        self.assertIn('class_ids', campaign.recipient_filter)


class EmailCampaignListViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_campaign_list_get(self):
        resp = self.client.get(reverse('email_campaign_list'))
        self.assertEqual(resp.status_code, 200)


class EmailCampaignDetailViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')
        self.campaign = EmailCampaign.objects.create(
            name='Test', subject='Test', html_body='<p>Test</p>',
            school=self.data['school'], created_by=self.data['hoi'],
        )

    def test_campaign_detail_get(self):
        url = reverse('email_campaign_detail', args=[self.campaign.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


class UnsubscribeViewTests(TestCase):
    def setUp(self):
        self.user = _create_user('unsub_user')
        self.pref = EmailPreference.objects.create(
            user=self.user, receive_campaigns=True,
        )

    def test_unsubscribe(self):
        url = reverse('email_unsubscribe', args=[self.pref.unsubscribe_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.pref.refresh_from_db()
        self.assertFalse(self.pref.receive_campaigns)


# ===========================================================================
# SALARY VIEWS
# ===========================================================================

class SalaryRateConfigurationViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_rate_config_get(self):
        resp = self.client.get(reverse('salary_rate_configuration'))
        self.assertEqual(resp.status_code, 200)

    def test_rate_config_no_school(self):
        user = _create_user('norateuser')
        _assign_role(user, Role.HEAD_OF_INSTITUTE)
        self.client.login(username='norateuser', password='pass12345')
        resp = self.client.get(reverse('salary_rate_configuration'))
        self.assertEqual(resp.status_code, 302)


class SetSchoolDefaultRateViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_set_default_rate(self):
        resp = self.client.post(reverse('set_school_default_rate'), {
            'hourly_rate': '25.00',
            'effective_from': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TeacherHourlyRate.objects.filter(
            school=self.data['school'], hourly_rate=Decimal('25.00'),
        ).exists())

    def test_set_default_rate_invalid(self):
        resp = self.client.post(reverse('set_school_default_rate'), {
            'hourly_rate': 'abc',
            'effective_from': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TeacherHourlyRate.objects.filter(
            school=self.data['school'],
        ).exists())

    def test_set_default_rate_missing_date(self):
        resp = self.client.post(reverse('set_school_default_rate'), {
            'hourly_rate': '25.00',
            'effective_from': '',
        })
        self.assertEqual(resp.status_code, 302)


class AddTeacherRateOverrideViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_add_override(self):
        resp = self.client.post(reverse('add_teacher_rate_override'), {
            'teacher_id': str(self.data['teacher'].id),
            'hourly_rate': '30.00',
            'effective_from': '2026-01-01',
            'reason': 'Senior',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TeacherRateOverride.objects.filter(
            teacher=self.data['teacher'], hourly_rate=Decimal('30.00'),
        ).exists())

    def test_add_override_invalid_teacher(self):
        resp = self.client.post(reverse('add_teacher_rate_override'), {
            'teacher_id': '99999',
            'hourly_rate': '30.00',
            'effective_from': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TeacherRateOverride.objects.exists())


class SalarySlipListViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_salary_slip_list_get(self):
        resp = self.client.get(reverse('salary_slip_list'))
        self.assertEqual(resp.status_code, 200)

    def test_salary_slip_list_with_filters(self):
        resp = self.client.get(reverse('salary_slip_list'), {
            'status': 'issued',
            'q': 'John',
        })
        self.assertEqual(resp.status_code, 200)


class SalarySlipDetailViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')
        self.slip = SalarySlip.objects.create(
            slip_number='SAL-001',
            school=self.data['school'],
            teacher=self.data['teacher'],
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            calculated_amount=Decimal('500.00'),
            amount=Decimal('500.00'),
            status='issued',
            created_by=self.data['hoi'],
        )

    def test_salary_slip_detail_get(self):
        url = reverse('salary_slip_detail', args=[self.slip.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


class CancelSalarySlipViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def _create_slip(self, status='issued'):
        return SalarySlip.objects.create(
            slip_number=f'SAL-{uuid.uuid4().hex[:6]}',
            school=self.data['school'],
            teacher=self.data['teacher'],
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            calculated_amount=Decimal('500.00'),
            amount=Decimal('500.00'),
            status=status,
            created_by=self.data['hoi'],
        )

    def test_cancel_draft_deletes(self):
        slip = self._create_slip(status='draft')
        url = reverse('cancel_salary_slip', args=[slip.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(SalarySlip.objects.filter(id=slip.id).exists())

    def test_cancel_issued_requires_reason(self):
        slip = self._create_slip(status='issued')
        url = reverse('cancel_salary_slip', args=[slip.id])
        resp = self.client.post(url, {'cancellation_reason': ''})
        self.assertEqual(resp.status_code, 302)
        slip.refresh_from_db()
        self.assertEqual(slip.status, 'issued')

    @patch('classroom.views_salaries.svc.cancel_salary_slip')
    def test_cancel_issued_with_reason(self, mock_cancel):
        slip = self._create_slip(status='issued')
        url = reverse('cancel_salary_slip', args=[slip.id])
        resp = self.client.post(url, {'cancellation_reason': 'Error'})
        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_called_once()

    def test_cancel_already_cancelled(self):
        slip = self._create_slip(status='cancelled')
        url = reverse('cancel_salary_slip', args=[slip.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)


class RecordSalaryPaymentViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')
        self.slip = SalarySlip.objects.create(
            slip_number='SAL-PAY-001',
            school=self.data['school'],
            teacher=self.data['teacher'],
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            calculated_amount=Decimal('500.00'),
            amount=Decimal('500.00'),
            status='issued',
            created_by=self.data['hoi'],
        )

    @patch('classroom.views_salaries.svc.record_salary_payment')
    def test_record_payment(self, mock_record):
        url = reverse('record_salary_payment', args=[self.slip.id])
        resp = self.client.post(url, {
            'amount': '100.00',
            'payment_date': '2026-01-15',
            'payment_method': 'bank_transfer',
            'notes': 'Payment 1',
        })
        self.assertEqual(resp.status_code, 302)
        mock_record.assert_called_once()

    def test_record_payment_invalid_amount(self):
        url = reverse('record_salary_payment', args=[self.slip.id])
        resp = self.client.post(url, {
            'amount': 'abc',
            'payment_date': '2026-01-15',
        })
        self.assertEqual(resp.status_code, 302)

    def test_record_payment_on_draft(self):
        self.slip.status = 'draft'
        self.slip.save()
        url = reverse('record_salary_payment', args=[self.slip.id])
        resp = self.client.post(url, {
            'amount': '100.00',
            'payment_date': '2026-01-15',
        })
        self.assertEqual(resp.status_code, 302)


class GenerateSalarySlipsViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_generate_salary_slips_get(self):
        resp = self.client.get(reverse('generate_salary_slips'))
        self.assertEqual(resp.status_code, 200)

    def test_generate_salary_slips_missing_dates(self):
        resp = self.client.post(reverse('generate_salary_slips'), {
            'billing_period_start': '',
            'billing_period_end': '',
        })
        self.assertEqual(resp.status_code, 302)

    def test_generate_salary_slips_start_after_end(self):
        resp = self.client.post(reverse('generate_salary_slips'), {
            'billing_period_start': '2026-02-01',
            'billing_period_end': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)


class TeacherSearchAPIViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_teacher_search(self):
        resp = self.client.get(reverse('teacher_search_api'), {'q': 'John'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['results']), 1)

    def test_teacher_search_short_query(self):
        resp = self.client.get(reverse('teacher_search_api'), {'q': 'J'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['results']), 0)


# ===========================================================================
# INVOICING VIEWS
# ===========================================================================

class FeeConfigurationViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_fee_config_get(self):
        resp = self.client.get(reverse('fee_configuration'))
        self.assertEqual(resp.status_code, 200)


class InvoiceListViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_invoice_list_get(self):
        resp = self.client.get(reverse('invoice_list'))
        self.assertEqual(resp.status_code, 200)

    def test_invoice_list_with_filters(self):
        resp = self.client.get(reverse('invoice_list'), {
            'status': 'issued',
            'q': 'Jane',
        })
        self.assertEqual(resp.status_code, 200)


class InvoiceDetailViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')
        self.invoice = Invoice.objects.create(
            invoice_number='INV-001',
            school=self.data['school'],
            student=self.data['student'],
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('200.00'),
            amount=Decimal('200.00'),
            status='issued',
            created_by=self.data['hoi'],
        )

    def test_invoice_detail_get(self):
        url = reverse('invoice_detail', args=[self.invoice.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


class CancelInvoiceViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def _create_invoice(self, status='issued'):
        return Invoice.objects.create(
            invoice_number=f'INV-{uuid.uuid4().hex[:6]}',
            school=self.data['school'],
            student=self.data['student'],
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('200.00'),
            amount=Decimal('200.00'),
            status=status,
            created_by=self.data['hoi'],
        )

    def test_cancel_draft_deletes(self):
        inv = self._create_invoice(status='draft')
        url = reverse('cancel_invoice', args=[inv.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Invoice.objects.filter(id=inv.id).exists())

    def test_cancel_issued_requires_reason(self):
        inv = self._create_invoice(status='issued')
        url = reverse('cancel_invoice', args=[inv.id])
        resp = self.client.post(url, {'cancellation_reason': ''})
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'issued')

    def test_cancel_already_cancelled(self):
        inv = self._create_invoice(status='cancelled')
        url = reverse('cancel_invoice', args=[inv.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

    @patch('classroom.views_invoicing.svc.cancel_invoice')
    def test_cancel_issued_with_reason(self, mock_cancel):
        inv = self._create_invoice(status='issued')
        url = reverse('cancel_invoice', args=[inv.id])
        resp = self.client.post(url, {'cancellation_reason': 'Duplicate'})
        self.assertEqual(resp.status_code, 302)
        mock_cancel.assert_called_once()


class GenerateInvoicesViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_generate_invoices_get(self):
        resp = self.client.get(reverse('generate_invoices'))
        self.assertEqual(resp.status_code, 200)

    def test_generate_invoices_missing_dates(self):
        resp = self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '',
            'billing_period_end': '',
        })
        self.assertEqual(resp.status_code, 302)

    def test_generate_invoices_start_after_end(self):
        resp = self.client.post(reverse('generate_invoices'), {
            'billing_period_start': '2026-02-01',
            'billing_period_end': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)


class SetClassroomFeeViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_set_classroom_fee(self):
        url = reverse('set_classroom_fee', args=[self.data['classroom'].id])
        resp = self.client.post(url, {'fee_override': '15.00'})
        self.assertEqual(resp.status_code, 302)
        self.data['classroom'].refresh_from_db()
        self.assertEqual(self.data['classroom'].fee_override, Decimal('15.00'))

    def test_clear_classroom_fee(self):
        self.data['classroom'].fee_override = Decimal('10.00')
        self.data['classroom'].save()
        url = reverse('set_classroom_fee', args=[self.data['classroom'].id])
        resp = self.client.post(url, {'fee_override': ''})
        self.assertEqual(resp.status_code, 302)
        self.data['classroom'].refresh_from_db()
        self.assertIsNone(self.data['classroom'].fee_override)

    def test_set_classroom_fee_invalid(self):
        url = reverse('set_classroom_fee', args=[self.data['classroom'].id])
        resp = self.client.post(url, {'fee_override': 'abc'})
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# PROGRESS VIEWS
# ===========================================================================

class ProgressCriteriaListViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_PROGRESS_REPORTS)
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')

    def test_criteria_list_get(self):
        resp = self.client.get(reverse('progress_criteria_list'))
        self.assertEqual(resp.status_code, 200)

    def test_criteria_list_with_filters(self):
        resp = self.client.get(reverse('progress_criteria_list'), {
            'subject_id': str(self.data['subject'].id),
        })
        self.assertEqual(resp.status_code, 200)

    def test_criteria_list_post_create(self):
        resp = self.client.post(reverse('progress_criteria_list'), {
            'action': 'create',
            'name': 'Can count to 10',
            'subject': str(self.data['subject'].id),
            'level': str(self.data['level'].id),
            'description': 'Counting',
            'order': '1',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProgressCriteria.objects.filter(name='Can count to 10').exists())

    def test_criteria_list_post_create_missing_name(self):
        resp = self.client.post(reverse('progress_criteria_list'), {
            'action': 'create',
            'name': '',
            'subject': '',
        })
        self.assertEqual(resp.status_code, 302)

    def test_criteria_list_no_school(self):
        teacher2 = _create_user('teacher_no_school_progress')
        _assign_role(teacher2, Role.TEACHER)
        self.client.login(username='teacher_no_school_progress', password='pass12345')
        resp = self.client.get(reverse('progress_criteria_list'))
        self.assertEqual(resp.status_code, 302)


class ProgressCriteriaCreateViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_PROGRESS_REPORTS)
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')

    def test_criteria_create_get(self):
        resp = self.client.get(reverse('progress_criteria_create'))
        self.assertEqual(resp.status_code, 200)

    def test_criteria_create_post(self):
        resp = self.client.post(reverse('progress_criteria_create'), {
            'name': 'Addition',
            'subject': str(self.data['subject'].id),
            'level': str(self.data['level'].id),
            'description': 'Basic addition',
            'order': '1',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProgressCriteria.objects.filter(name='Addition').exists())

    def test_criteria_create_post_missing_fields(self):
        resp = self.client.post(reverse('progress_criteria_create'), {
            'name': '',
            'subject': '',
        })
        self.assertEqual(resp.status_code, 200)


class ProgressCriteriaWorkflowTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_PROGRESS_REPORTS)
        # Make the teacher a senior teacher for approval
        _assign_role(self.data['teacher'], Role.SENIOR_TEACHER)
        self.client = Client()
        self.criteria = ProgressCriteria.objects.create(
            school=self.data['school'],
            subject=self.data['subject'],
            level=self.data['level'],
            name='Test Criteria',
            status='draft',
            created_by=self.data['teacher'],
        )

    def test_submit_criteria(self):
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('progress_criteria_submit', args=[self.criteria.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.criteria.refresh_from_db()
        self.assertEqual(self.criteria.status, 'pending_approval')

    def test_submit_non_draft_fails(self):
        self.criteria.status = 'approved'
        self.criteria.save()
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('progress_criteria_submit', args=[self.criteria.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.criteria.refresh_from_db()
        self.assertEqual(self.criteria.status, 'approved')

    def test_approval_list(self):
        self.criteria.status = 'pending_approval'
        self.criteria.save()
        self.client.login(username='teacher1', password='pass12345')
        resp = self.client.get(reverse('progress_criteria_approvals'))
        self.assertEqual(resp.status_code, 200)

    def test_approve_criteria(self):
        self.criteria.status = 'pending_approval'
        self.criteria.save()
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('progress_criteria_approve', args=[self.criteria.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.criteria.refresh_from_db()
        self.assertEqual(self.criteria.status, 'approved')

    def test_reject_criteria(self):
        self.criteria.status = 'pending_approval'
        self.criteria.save()
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('progress_criteria_reject', args=[self.criteria.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.criteria.refresh_from_db()
        self.assertEqual(self.criteria.status, 'rejected')

    def test_approve_non_pending_fails(self):
        self.criteria.status = 'draft'
        self.criteria.save()
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('progress_criteria_approve', args=[self.criteria.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.criteria.refresh_from_db()
        self.assertEqual(self.criteria.status, 'draft')


class RecordProgressViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_PROGRESS_REPORTS)
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')
        self.criteria = ProgressCriteria.objects.create(
            school=self.data['school'],
            subject=self.data['subject'],
            level=self.data['level'],
            name='Count to 10',
            status='approved',
            created_by=self.data['teacher'],
        )

    def test_record_progress_get(self):
        url = reverse('record_progress', args=[self.data['classroom'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_record_progress_post(self):
        url = reverse('record_progress', args=[self.data['classroom'].id])
        student = self.data['student']
        resp = self.client.post(url, {
            f'status_{student.id}_{self.criteria.id}': 'achieved',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProgressRecord.objects.filter(
            student=student, criteria=self.criteria, status='achieved',
        ).exists())


class StudentProgressViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_PROGRESS_REPORTS)
        self.client = Client()
        self.client.login(username='teacher1', password='pass12345')
        self.criteria = ProgressCriteria.objects.create(
            school=self.data['school'],
            subject=self.data['subject'],
            level=self.data['level'],
            name='Count to 10',
            status='approved',
            created_by=self.data['teacher'],
        )
        ProgressRecord.objects.create(
            student=self.data['student'],
            criteria=self.criteria,
            status='achieved',
            recorded_by=self.data['teacher'],
        )

    def test_student_progress_get(self):
        url = reverse('student_progress', args=[self.data['student'].id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['overall']['achieved'], 1)


class StudentProgressReportViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        _enable_module(self.data['sub'], ModuleSubscription.MODULE_PROGRESS_REPORTS)
        self.client = Client()
        # HoI needs to see the report
        _assign_role(self.data['hoi'], Role.INSTITUTE_OWNER)
        self.client.login(username='hoi', password='pass12345')

    def test_progress_report_get(self):
        resp = self.client.get(reverse('student_progress_report'))
        self.assertEqual(resp.status_code, 200)

    def test_progress_report_with_filters(self):
        resp = self.client.get(reverse('student_progress_report'), {
            'department': str(self.data['dept'].id),
            'subject': str(self.data['subject'].id),
        })
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# BATCH VIEWS (additional coverage)
# ===========================================================================

class BatchTeacherRateViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_batch_teacher_rate(self):
        tid = self.data['teacher'].id
        resp = self.client.post(reverse('batch_teacher_rate'), {
            'teacher_ids': str(tid),
            'effective_from': '2026-01-01',
            f'rate_{tid}': '35.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TeacherRateOverride.objects.filter(
            teacher=self.data['teacher'], hourly_rate=Decimal('35.00'),
        ).exists())

    def test_batch_teacher_rate_missing_date(self):
        tid = self.data['teacher'].id
        resp = self.client.post(reverse('batch_teacher_rate'), {
            'teacher_ids': str(tid),
            'effective_from': '',
            f'rate_{tid}': '35.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TeacherRateOverride.objects.exists())


class DeleteDraftSalarySlipsViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')
        self.slip = SalarySlip.objects.create(
            slip_number='SAL-DRAFT-001',
            school=self.data['school'],
            teacher=self.data['teacher'],
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 1, 31),
            calculated_amount=Decimal('500.00'),
            amount=Decimal('500.00'),
            status='draft',
            created_by=self.data['hoi'],
        )

    def test_delete_draft_slips(self):
        session = self.client.session
        session['draft_salary_slip_ids'] = [self.slip.id]
        session.save()
        resp = self.client.post(reverse('delete_draft_salary_slips'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(SalarySlip.objects.filter(id=self.slip.id).exists())


class BatchClassroomFeeViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_batch_classroom_fee(self):
        cid = self.data['classroom'].id
        resp = self.client.post(reverse('batch_classroom_fee'), {
            'classroom_ids': str(cid),
            f'fee_{cid}': '20.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.data['classroom'].refresh_from_db()
        self.assertEqual(self.data['classroom'].fee_override, Decimal('20.00'))

    def test_batch_classroom_fee_clear(self):
        self.data['classroom'].fee_override = Decimal('10.00')
        self.data['classroom'].save()
        cid = self.data['classroom'].id
        resp = self.client.post(reverse('batch_classroom_fee'), {
            'classroom_ids': str(cid),
            f'fee_{cid}': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.data['classroom'].refresh_from_db()
        self.assertIsNone(self.data['classroom'].fee_override)


class AddStudentFeeOverrideViewTests(TestCase):
    def setUp(self):
        self.data = _full_school_setup()
        self.client = Client()
        self.client.login(username='hoi', password='pass12345')

    def test_add_student_fee_override(self):
        resp = self.client.post(reverse('add_student_fee_override'), {
            'student_id': str(self.data['student'].id),
            'daily_rate': '12.50',
            'effective_from': '2026-01-01',
            'reason': 'Discount',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(StudentFeeOverride.objects.filter(
            student=self.data['student'], daily_rate=Decimal('12.50'),
        ).exists())

    def test_add_student_fee_override_invalid_student(self):
        resp = self.client.post(reverse('add_student_fee_override'), {
            'student_id': '99999',
            'daily_rate': '12.50',
            'effective_from': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StudentFeeOverride.objects.exists())

    def test_add_student_fee_override_invalid_rate(self):
        resp = self.client.post(reverse('add_student_fee_override'), {
            'student_id': str(self.data['student'].id),
            'daily_rate': 'abc',
            'effective_from': '2026-01-01',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StudentFeeOverride.objects.exists())
