"""
Unit tests for CPP-300 per-class bulk "Resend Welcome".

Covers BulkResendWelcomeView:
  * regenerates a temp password and emails each selected student
  * fans out to each selected student's active linked parents
  * only affects the selected students
  * skips recipients with no email and reports the count
  * sets must_change_password=True on institute accounts
  * tenant isolation — a cross-school class id 404s
  * permission denied for parent role and for a teacher of another class
  * empty selection is a graceful no-op
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, SchoolTeacher, Department, Subject, Level,
    ClassRoom, ClassStudent, ClassTeacher, ParentStudent,
)


def _make_user(username, role_name, email='', creation_method='institute'):
    user = CustomUser.objects.create_user(
        username=username,
        email=email or f'{username}@example.local',
        password='TestPass123!',
        first_name=username.capitalize(),
        last_name='Test',
    )
    if email == '__none__':
        user.email = None
        user.save(update_fields=['email'])
    user.creation_method = creation_method
    user.save(update_fields=['creation_method'])
    role, _ = Role.objects.get_or_create(
        name=role_name, defaults={'display_name': role_name.title()},
    )
    UserRole.objects.create(user=user, role=role)
    return user


class BulkResendWelcomeBase(TestCase):
    def setUp(self):
        self.hoi = _make_user('hoi_bulk', Role.HEAD_OF_INSTITUTE)
        self.school = School.objects.create(
            name='Bulk School', slug='bulk-school', admin=self.hoi,
            is_active=True, is_published=True,
        )
        SchoolTeacher.objects.get_or_create(
            school=self.school, teacher=self.hoi,
            defaults={'role': 'head_of_institute', 'is_active': True},
        )
        self.subject = Subject.objects.create(name='Maths', slug='maths-bulk', school=self.school)
        self.dept = Department.objects.create(
            school=self.school, name='Maths Dept', slug='maths-dept-bulk', head=self.hoi,
        )
        self.classroom = ClassRoom.objects.create(
            name='Class A', school=self.school, department=self.dept, subject=self.subject,
        )

        self.teacher = _make_user('tch_bulk', Role.TEACHER)
        SchoolTeacher.objects.create(
            school=self.school, teacher=self.teacher, role='teacher', is_active=True,
        )
        ClassTeacher.objects.create(classroom=self.classroom, teacher=self.teacher)

        # Two enrolled students; student1 has a linked parent.
        self.student1 = self._enrol('stu1_bulk')
        self.student2 = self._enrol('stu2_bulk')
        self.parent1 = _make_user('par1_bulk', Role.PARENT)
        ParentStudent.objects.create(
            parent=self.parent1, student=self.student1, school=self.school,
            relationship='guardian', is_active=True,
        )

        self.url = reverse('class_bulk_resend_welcome', args=[self.classroom.id])

    def _enrol(self, username, email=''):
        student = _make_user(username, Role.STUDENT, email=email)
        SchoolStudent.objects.create(school=self.school, student=student, is_active=True)
        ClassStudent.objects.create(classroom=self.classroom, student=student, is_active=True)
        return student


class BulkResendWelcomeTests(BulkResendWelcomeBase):

    def test_bulk_resend_regenerates_password_and_emails_selected(self):
        self.client.force_login(self.hoi)
        old_hash = self.student1.password
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            resp = self.client.post(self.url, {'student_ids': [self.student1.id]})
        self.assertEqual(resp.status_code, 302)
        self.student1.refresh_from_db()
        self.assertNotEqual(self.student1.password, old_hash)  # password regenerated
        # student + their parent both emailed
        recipients = {c.args[0].id for c in mock_send.call_args_list}
        self.assertIn(self.student1.id, recipients)
        self.assertIn(self.parent1.id, recipients)

    def test_bulk_resend_emails_linked_parents_of_selected_student(self):
        self.client.force_login(self.hoi)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            self.client.post(self.url, {'student_ids': [self.student1.id]})
        emailed = {c.args[0].id for c in mock_send.call_args_list}
        self.assertEqual(emailed, {self.student1.id, self.parent1.id})

    def test_bulk_resend_shared_parent_emailed_once(self):
        """A parent linked to two selected siblings is emailed exactly once."""
        ParentStudent.objects.create(
            parent=self.parent1, student=self.student2, school=self.school,
            relationship='guardian', is_active=True,
        )
        self.client.force_login(self.hoi)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            self.client.post(
                self.url, {'student_ids': [self.student1.id, self.student2.id]},
            )
        parent_calls = [
            c for c in mock_send.call_args_list if c.args[0].id == self.parent1.id
        ]
        self.assertEqual(len(parent_calls), 1)

    def test_bulk_resend_only_affects_selected_students(self):
        self.client.force_login(self.hoi)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            self.client.post(self.url, {'student_ids': [self.student2.id]})
        emailed = {c.args[0].id for c in mock_send.call_args_list}
        self.assertIn(self.student2.id, emailed)
        self.assertNotIn(self.student1.id, emailed)
        self.assertNotIn(self.parent1.id, emailed)

    def test_bulk_resend_skips_students_without_email(self):
        no_email_student = self._enrol('stu_noemail_bulk', email='__none__')
        self.client.force_login(self.hoi)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            self.client.post(self.url, {'student_ids': [no_email_student.id]})
        # No send attempted for an email-less recipient.
        self.assertEqual(mock_send.call_count, 0)

    def test_bulk_resend_sets_must_change_password_true(self):
        self.student1.must_change_password = False
        self.student1.save(update_fields=['must_change_password'])
        self.client.force_login(self.hoi)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ):
            self.client.post(self.url, {'student_ids': [self.student1.id]})
        self.student1.refresh_from_db()
        self.assertTrue(self.student1.must_change_password)

    def test_bulk_resend_empty_selection_noops_gracefully(self):
        self.client.force_login(self.hoi)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            resp = self.client.post(self.url, {'student_ids': []})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(mock_send.call_count, 0)

    def test_teacher_can_bulk_resend_own_class(self):
        self.client.force_login(self.teacher)
        with patch(
            'classroom.views_password_admin._send_resend_welcome_email',
            return_value=True,
        ) as mock_send:
            resp = self.client.post(self.url, {'student_ids': [self.student1.id]})
        self.assertEqual(resp.status_code, 302)
        self.assertGreaterEqual(mock_send.call_count, 1)


class BulkResendWelcomePermissionTests(BulkResendWelcomeBase):

    def test_bulk_resend_cross_school_class_returns_404(self):
        """An admin of another school cannot resend for this class."""
        other_admin = _make_user('other_hoi_bulk', Role.HEAD_OF_INSTITUTE)
        School.objects.create(
            name='Other School', slug='other-school-bulk', admin=other_admin,
            is_active=True,
        )
        self.client.force_login(other_admin)
        resp = self.client.post(self.url, {'student_ids': [self.student1.id]})
        self.assertEqual(resp.status_code, 404)

    def test_bulk_resend_permission_denied_for_parent(self):
        self.client.force_login(self.parent1)
        resp = self.client.post(self.url, {'student_ids': [self.student1.id]})
        # RoleRequiredMixin blocks non-staff roles (redirect or 403, never 302→success).
        self.assertIn(resp.status_code, (302, 403))
        if resp.status_code == 302:
            self.assertNotIn(f'/class/{self.classroom.id}/', resp.url)

    def test_bulk_resend_permission_denied_for_teacher_of_other_class(self):
        """A teacher who doesn't teach this class is 404'd (tenant/scope isolation)."""
        other_teacher = _make_user('other_tch_bulk', Role.TEACHER)
        SchoolTeacher.objects.create(
            school=self.school, teacher=other_teacher, role='teacher', is_active=True,
        )
        # Note: other_teacher is NOT a ClassTeacher of self.classroom.
        self.client.force_login(other_teacher)
        resp = self.client.post(self.url, {'student_ids': [self.student1.id]})
        self.assertEqual(resp.status_code, 404)
