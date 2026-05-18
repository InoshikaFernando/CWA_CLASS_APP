"""
Tests for CPP-273 (remove teacher from class) and CPP-274 (set fee to 0).
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import ClassRoom, ClassTeacher, ClassStudent, School, Department


def _ensure_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


class _ClassPageTestBase(TestCase):
    """Shared setup for class page bug tests."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_cpb', password='pass', email='admin_cpb@test.com',
        )
        UserRole.objects.create(user=cls.admin, role=_ensure_role(Role.ADMIN))

        cls.school = School.objects.create(name='Test School CPB', admin=cls.admin)
        cls.dept = Department.objects.create(school=cls.school, name='Dept CPB')
        cls.classroom = ClassRoom.objects.create(
            name='Class CPB', school=cls.school, department=cls.dept, code='CPB001',
        )

        cls.teacher = CustomUser.objects.create_user(
            username='teacher_cpb', password='pass', email='teacher_cpb@test.com',
        )
        UserRole.objects.create(user=cls.teacher, role=_ensure_role(Role.TEACHER))
        cls.ct = ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        cls.student = CustomUser.objects.create_user(
            username='student_cpb', password='pass', email='student_cpb@test.com',
        )
        UserRole.objects.create(user=cls.student, role=_ensure_role(Role.STUDENT))
        cls.cs = ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student,
        )


class TestRemoveTeacherFromClass(_ClassPageTestBase):
    """CPP-273: Cannot remove a teacher from a class."""

    def test_admin_can_remove_teacher(self):
        client = Client()
        client.login(username='admin_cpb', password='pass')
        url = reverse('class_teacher_remove', kwargs={
            'class_id': self.classroom.id, 'teacher_id': self.teacher.id,
        })
        resp = client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ClassTeacher.objects.filter(classroom=self.classroom, teacher=self.teacher).exists()
        )

    def test_teacher_cannot_remove_teacher(self):
        """Regular teachers should not be able to remove other teachers."""
        client = Client()
        client.login(username='teacher_cpb', password='pass')
        url = reverse('class_teacher_remove', kwargs={
            'class_id': self.classroom.id, 'teacher_id': self.teacher.id,
        })
        resp = client.post(url)
        # Should be forbidden (redirect to login or 404)
        self.assertIn(resp.status_code, [302, 403, 404])
        # Teacher should still exist
        self.assertTrue(
            ClassTeacher.objects.filter(classroom=self.classroom, teacher=self.teacher).exists()
        )

    def test_remove_nonexistent_teacher(self):
        """Removing a teacher not in the class shows a warning, doesn't crash."""
        client = Client()
        client.login(username='admin_cpb', password='pass')
        url = reverse('class_teacher_remove', kwargs={
            'class_id': self.classroom.id, 'teacher_id': 99999,
        })
        resp = client.post(url)
        self.assertEqual(resp.status_code, 302)

    def test_url_resolves(self):
        """The class_teacher_remove URL pattern exists."""
        url = reverse('class_teacher_remove', kwargs={
            'class_id': 1, 'teacher_id': 1,
        })
        self.assertIn('/teacher/', url)
        self.assertIn('/remove/', url)


class TestSetFeeToZero(_ClassPageTestBase):
    """CPP-274: Cannot set the fee to 0 for a given student in class page."""

    def _post_fee(self, fee_value):
        client = Client()
        client.login(username='admin_cpb', password='pass')
        url = reverse('update_student_fee', kwargs={
            'class_id': self.classroom.id, 'student_id': self.student.id,
        })
        return client.post(url, {'fee_override': str(fee_value)})

    def test_fee_zero_is_saved(self):
        """Setting fee to 0 should save Decimal('0'), not None."""
        resp = self._post_fee('0')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        self.assertEqual(self.cs.fee_override, Decimal('0'))

    def test_fee_zero_decimal_is_saved(self):
        """Setting fee to 0.00 should save Decimal('0.00'), not None."""
        resp = self._post_fee('0.00')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        # Decimal('0.00') == Decimal('0')
        self.assertEqual(self.cs.fee_override, Decimal('0'))

    def test_fee_positive_is_saved(self):
        """Positive fees should work as before."""
        resp = self._post_fee('50.00')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        self.assertEqual(self.cs.fee_override, Decimal('50.00'))

    def test_fee_negative_is_rejected(self):
        """Negative fees should be rejected."""
        resp = self._post_fee('-10')
        self.assertEqual(resp.status_code, 302)
        self.cs.refresh_from_db()
        # Should remain unchanged (None by default)
        self.assertIsNone(self.cs.fee_override)

    def test_fee_empty_clears_override(self):
        """Empty fee string should clear the override to None."""
        # First set a fee
        self._post_fee('25')
        self.cs.refresh_from_db()
        self.assertEqual(self.cs.fee_override, Decimal('25'))

        # Now clear it
        client = Client()
        client.login(username='admin_cpb', password='pass')
        url = reverse('update_student_fee', kwargs={
            'class_id': self.classroom.id, 'student_id': self.student.id,
        })
        client.post(url, {'fee_override': ''})
        self.cs.refresh_from_db()
        self.assertIsNone(self.cs.fee_override)
