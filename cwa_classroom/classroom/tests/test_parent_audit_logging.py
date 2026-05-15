"""
classroom/tests/test_parent_audit_logging.py — Audit logging tests for parent
read-access views (CPP-271).
"""
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from classroom.models import (
    School, SchoolStudent, ParentStudent, ClassRoom, ClassStudent, Subject,
)


class ParentAuditLoggingTestBase(TestCase):
    """Shared fixtures for parent audit logging tests."""

    @classmethod
    def setUpTestData(cls):
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )

        cls.admin_user = CustomUser.objects.create_user(
            'admin', 'admin@test.com', 'password1!',
        )
        cls.admin_user.roles.add(cls.admin_role)
        cls.school = School.objects.create(
            name='Audit School', slug='audit-school', admin=cls.admin_user,
        )

        cls.student = CustomUser.objects.create_user(
            'student1', 'student1@test.com', 'password1!',
            first_name='Zara', last_name='Student',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        cls.parent = CustomUser.objects.create_user(
            'parent1', 'parent1@test.com', 'password1!',
            first_name='Jane', last_name='Parent',
        )
        cls.parent.roles.add(cls.parent_role)
        cls.link = ParentStudent.objects.create(
            parent=cls.parent, student=cls.student,
            school=cls.school, relationship='mother',
        )

        # Second child for multi-child test
        cls.student2 = CustomUser.objects.create_user(
            'student2', 'student2@test.com', 'password1!',
            first_name='Leo', last_name='Student',
        )
        cls.student2.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student2)
        cls.link2 = ParentStudent.objects.create(
            parent=cls.parent, student=cls.student2,
            school=cls.school, relationship='mother',
        )

        # Class + enrollment (needed for homework/classes views)
        cls.maths, _ = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.classroom = ClassRoom.objects.create(
            name='Maths Year 7', school=cls.school, subject=cls.maths,
        )
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student,
        )

    def setUp(self):
        self.client = Client()
        AuditLog.objects.all().delete()

    def _login_and_set_active_child(self, child):
        """Login as parent and set the active child in session."""
        self.client.login(username='parent1', password='password1!')
        session = self.client.session
        session['active_child_id'] = child.id
        session.save()


class TestParentViewHomeworkAuditLog(ParentAuditLoggingTestBase):

    def test_parent_view_homework_logs_event(self):
        self._login_and_set_active_child(self.student)
        url = reverse('parent_homework')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='parent_viewed_homework').first()
        self.assertIsNotNone(log, 'No parent_viewed_homework audit log found')
        self.assertEqual(log.user, self.parent)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.category, 'data_change')
        self.assertEqual(log.detail['child_id'], self.student.id)
        self.assertIn('child_name', log.detail)


class TestParentViewAttendanceAuditLog(ParentAuditLoggingTestBase):

    def test_parent_view_attendance_logs_event(self):
        self._login_and_set_active_child(self.student)
        url = reverse('parent_attendance')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='parent_viewed_attendance').first()
        self.assertIsNotNone(log, 'No parent_viewed_attendance audit log found')
        self.assertEqual(log.user, self.parent)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.detail['child_id'], self.student.id)


class TestParentViewProgressAuditLog(ParentAuditLoggingTestBase):

    def test_parent_view_progress_logs_event(self):
        self._login_and_set_active_child(self.student)
        url = reverse('parent_progress')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='parent_viewed_progress').first()
        self.assertIsNotNone(log, 'No parent_viewed_progress audit log found')
        self.assertEqual(log.user, self.parent)
        self.assertEqual(log.detail['child_id'], self.student.id)


class TestParentViewInvoicesAuditLog(ParentAuditLoggingTestBase):

    def test_parent_view_invoices_logs_event(self):
        self._login_and_set_active_child(self.student)
        url = reverse('parent_invoices')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='parent_viewed_invoices').first()
        self.assertIsNotNone(log, 'No parent_viewed_invoices audit log found')
        self.assertEqual(log.user, self.parent)
        self.assertEqual(log.detail['child_id'], self.student.id)


class TestParentViewClassesAuditLog(ParentAuditLoggingTestBase):

    def test_parent_view_classes_logs_event(self):
        self._login_and_set_active_child(self.student)
        url = reverse('parent_classes')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='parent_viewed_classes').first()
        self.assertIsNotNone(log, 'No parent_viewed_classes audit log found')
        self.assertEqual(log.user, self.parent)
        self.assertEqual(log.detail['child_id'], self.student.id)


class TestMultiChildParentAuditLog(ParentAuditLoggingTestBase):

    def test_multi_child_parent_logs_correct_child(self):
        """Switch to child2 then view homework — log should reference child2."""
        self.client.login(username='parent1', password='password1!')

        # Switch to second child
        switch_url = reverse('parent_switch_child', kwargs={
            'student_id': self.student2.id,
        })
        self.client.post(switch_url)

        # View homework — should log child2
        AuditLog.objects.all().delete()
        url = reverse('parent_homework')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='parent_viewed_homework').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.detail['child_id'], self.student2.id)
        self.assertIn('Leo', log.detail['child_name'])


class TestParentViewNoChildDoesNotLog(ParentAuditLoggingTestBase):

    def test_parent_view_no_child_does_not_log(self):
        """Parent with no linked children should not produce a log."""
        unlinked_parent = CustomUser.objects.create_user(
            'lonely_parent', 'lonely@test.com', 'password1!',
        )
        unlinked_parent.roles.add(self.parent_role)

        self.client.login(username='lonely_parent', password='password1!')
        url = reverse('parent_homework')
        self.client.get(url)

        self.assertFalse(
            AuditLog.objects.filter(action='parent_viewed_homework').exists(),
            'Should not log when parent has no linked children',
        )


class TestParentAuditResilience(ParentAuditLoggingTestBase):

    def test_log_event_failure_does_not_break_parent_view(self):
        """Audit log failure must not break the parent homework view."""
        self._login_and_set_active_child(self.student)
        url = reverse('parent_homework')

        with patch('audit.models.AuditLog.objects.create', side_effect=Exception('DB down')):
            resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
