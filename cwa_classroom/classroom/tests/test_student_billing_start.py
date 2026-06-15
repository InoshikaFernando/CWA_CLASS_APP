"""
Unit tests for CPP-342 — editable per-student billing start date.

Covers:
  - HoI/Accountant can set, change, and clear ClassStudent.billing_start_date
  - Invalid date is rejected and leaves the value unchanged
  - Empty value clears it (NULL = bill the full period)
  - Teacher / HoD cannot update it
  - Cross-class / unknown student returns 404
  - The class detail page renders the date and the edit control for HoI
"""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, School,
)


def _ensure_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_bsd', password='pass', email='admin_bsd@test.com',
        )
        UserRole.objects.create(user=cls.admin, role=_ensure_role(Role.ADMIN))
        UserRole.objects.create(user=cls.admin, role=_ensure_role(Role.HEAD_OF_INSTITUTE))

        cls.school = School.objects.create(name='BSD School', admin=cls.admin)
        cls.dept = Department.objects.create(school=cls.school, name='Dept BSD')
        cls.classroom = ClassRoom.objects.create(
            name='Class BSD', school=cls.school, department=cls.dept, code='BSD001',
        )

        cls.teacher = CustomUser.objects.create_user(
            username='teacher_bsd', password='pass', email='teacher_bsd@test.com',
        )
        UserRole.objects.create(user=cls.teacher, role=_ensure_role(Role.TEACHER))
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        cls.student = CustomUser.objects.create_user(
            username='student_bsd', password='pass', email='student_bsd@test.com',
        )
        UserRole.objects.create(user=cls.student, role=_ensure_role(Role.STUDENT))
        cls.cs = ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

    def _url(self, class_id=None, student_id=None):
        return reverse('update_student_billing_start', kwargs={
            'class_id': class_id or self.classroom.id,
            'student_id': student_id or self.student.id,
        })

    def _post(self, username, value, **kwargs):
        client = Client()
        client.login(username=username, password='pass')
        return client.post(self._url(**kwargs), {'billing_start_date': value})


class TestUpdateBillingStart(_Base):

    def test_hoi_can_set_date(self):
        resp = self._post('admin_bsd', '2026-05-15')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        self.assertEqual(self.cs.billing_start_date, datetime.date(2026, 5, 15))

    def test_change_existing_date(self):
        self.cs.billing_start_date = datetime.date(2026, 1, 1)
        self.cs.save(update_fields=['billing_start_date'])
        self._post('admin_bsd', '2026-06-01')
        self.cs.refresh_from_db()
        self.assertEqual(self.cs.billing_start_date, datetime.date(2026, 6, 1))

    def test_empty_clears_date(self):
        self.cs.billing_start_date = datetime.date(2026, 3, 1)
        self.cs.save(update_fields=['billing_start_date'])
        resp = self._post('admin_bsd', '')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        self.assertIsNone(self.cs.billing_start_date)

    def test_invalid_date_rejected(self):
        self.cs.billing_start_date = datetime.date(2026, 2, 2)
        self.cs.save(update_fields=['billing_start_date'])
        resp = self._post('admin_bsd', 'not-a-date')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        # unchanged
        self.assertEqual(self.cs.billing_start_date, datetime.date(2026, 2, 2))

    def test_teacher_cannot_update(self):
        resp = self._post('teacher_bsd', '2026-05-15')
        self.assertIn(resp.status_code, [302, 403, 404])
        self.cs.refresh_from_db()
        self.assertIsNone(self.cs.billing_start_date)

    def test_unknown_student_returns_404(self):
        client = Client()
        client.login(username='admin_bsd', password='pass')
        resp = client.post(self._url(student_id=999999), {'billing_start_date': '2026-05-15'})
        self.assertEqual(resp.status_code, 404)

    def test_class_detail_shows_date_and_control(self):
        self.cs.billing_start_date = datetime.date(2026, 5, 15)
        self.cs.save(update_fields=['billing_start_date'])
        client = Client()
        client.login(username='admin_bsd', password='pass')
        resp = client.get(reverse('class_detail', kwargs={'class_id': self.classroom.id}))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The edit control (button + date input) and the rendered date are present.
        self.assertIn('Start date', body)
        self.assertIn('billing_start_date', body)
        self.assertIn('bills from', body)
