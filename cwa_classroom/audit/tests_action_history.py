"""Tests for the staff Action History + revert feature."""
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from accounts.models import Role, UserRole
from classroom.models import School, ClassRoom, ClassStudent, Enrollment
from audit.models import AuditLog
from audit.services import log_event
from audit.reverters import REVERTIBLE_ACTIONS

User = get_user_model()


class ActionHistoryRevertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.staff = User.objects.create_user(
            username='staff1', password='password1!', email='staff1@test.com')
        UserRole.objects.create(user=cls.staff, role=cls.teacher_role)
        cls.school = School.objects.create(name='Test School', admin=cls.staff)
        cls.student = User.objects.create_user(
            username='stud1', password='password1!', email='stud1@test.com',
            first_name='Test', last_name='Student')
        cls.classroom = ClassRoom.objects.create(
            name='Y5 Maths', school=cls.school, code='ABCD1234')

    def test_log_event_sets_is_revertible(self):
        log_event(user=self.staff, school=self.school, category='data_change',
                  action='class_student_removed',
                  detail={'class_id': self.classroom.id, 'student_id': self.student.id})
        self.assertTrue(AuditLog.objects.get(action='class_student_removed').is_revertible)

    def test_non_revertible_action(self):
        log_event(user=self.staff, category='auth', action='login_success')
        self.assertFalse(AuditLog.objects.get(action='login_success').is_revertible)

    def test_action_history_page_loads(self):
        self.client.login(username='staff1', password='password1!')
        self.assertEqual(self.client.get(reverse('action_history')).status_code, 200)

    def test_revert_class_student_removed(self):
        cs = ClassStudent.objects.create(
            classroom=self.classroom, student=self.student, is_active=False)
        Enrollment.objects.create(
            classroom=self.classroom, student=self.student, status='removed')
        log_event(user=self.staff, school=self.school, category='data_change',
                  action='class_student_removed',
                  detail={'class_id': self.classroom.id, 'student_id': self.student.id})
        entry = AuditLog.objects.get(action='class_student_removed')
        self.client.login(username='staff1', password='password1!')
        resp = self.client.post(reverse('revert_action', args=[entry.id]))
        self.assertEqual(resp.status_code, 302)
        cs.refresh_from_db()
        self.assertTrue(cs.is_active)
        self.assertEqual(Enrollment.objects.get(
            classroom=self.classroom, student=self.student).status, 'approved')
        entry.refresh_from_db()
        self.assertIsNotNone(entry.reverted_at)
        self.assertEqual(entry.reverted_by, self.staff)

    def test_double_revert_blocked(self):
        ClassStudent.objects.create(
            classroom=self.classroom, student=self.student, is_active=False)
        log_event(user=self.staff, school=self.school, category='data_change',
                  action='class_student_removed',
                  detail={'class_id': self.classroom.id, 'student_id': self.student.id})
        entry = AuditLog.objects.get(action='class_student_removed')
        self.client.login(username='staff1', password='password1!')
        self.client.post(reverse('revert_action', args=[entry.id]))
        self.assertEqual(
            self.client.post(reverse('revert_action', args=[entry.id])).status_code, 302)

    def test_cannot_revert_other_users_action(self):
        other = User.objects.create_user(
            username='other', password='password1!', email='other@test.com')
        UserRole.objects.create(user=other, role=self.teacher_role)
        log_event(user=other, school=self.school, category='data_change',
                  action='class_student_removed',
                  detail={'class_id': self.classroom.id, 'student_id': self.student.id})
        entry = AuditLog.objects.get(action='class_student_removed')
        self.client.login(username='staff1', password='password1!')
        self.assertEqual(
            self.client.post(reverse('revert_action', args=[entry.id])).status_code, 404)

    def test_registry_functions_callable(self):
        for action, (fn, label) in REVERTIBLE_ACTIONS.items():
            self.assertTrue(callable(fn))
            self.assertIsInstance(label, str)

    def test_student_enrolled_not_revertible(self):
        # Bulk enrol logs only a count, so it must not be revertible.
        self.assertNotIn('student_enrolled', REVERTIBLE_ACTIONS)

    def test_teacher_cannot_revert_elevated_action(self):
        # A plain teacher (NOT a school admin) owns a school_toggled_active log
        # but lacks an elevated role, so the revert is denied at revert time.
        teacher = User.objects.create_user(
            username='plainteacher', password='password1!', email='pt@test.com')
        UserRole.objects.create(user=teacher, role=self.teacher_role)
        log_event(user=teacher, school=self.school, category='data_change',
                  action='school_toggled_active',
                  detail={'school_id': self.school.id, 'is_active': False})
        entry = AuditLog.objects.get(action='school_toggled_active')
        self.client.login(username='plainteacher', password='password1!')
        resp = self.client.post(reverse('revert_action', args=[entry.id]))
        self.assertEqual(resp.status_code, 302)
        entry.refresh_from_db()
        self.assertIsNone(entry.reverted_at)  # not reverted — privilege denied

    def test_hoi_can_revert_school_toggle(self):
        # self.staff is the school's admin, which grants the HoI role -> allowed.
        hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'})
        UserRole.objects.get_or_create(user=self.staff, role=hoi_role)
        self.school.is_active = False
        self.school.save(update_fields=['is_active'])
        log_event(user=self.staff, school=self.school, category='data_change',
                  action='school_toggled_active',
                  detail={'school_id': self.school.id, 'is_active': False})
        entry = AuditLog.objects.get(action='school_toggled_active')
        self.client.login(username='staff1', password='password1!')
        resp = self.client.post(reverse('revert_action', args=[entry.id]))
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        self.assertTrue(self.school.is_active)  # reverted back to active

    def test_discount_code_toggle_reverter_uses_correct_key(self):
        # Reverter must read 'discount_id' (the key the logging site writes).
        from audit.reverters import REVERTIBLE_ACTIONS as RA
        fn, _ = RA['discount_code_toggled']
        entry = AuditLog(action='discount_code_toggled', detail={'plan_id': 1})
        with self.assertRaises(ValueError) as ctx:
            fn(entry)
        self.assertIn('discount_id', str(ctx.exception))