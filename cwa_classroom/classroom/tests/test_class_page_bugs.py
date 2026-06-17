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

    def test_fee_cross_tenant_write_blocked(self):
        """A privileged user of school A cannot set a fee in school B's class."""
        admin_b = CustomUser.objects.create_user(
            username='admin_b_cpb', password='pass', email='admin_b_cpb@test.com',
        )
        UserRole.objects.create(user=admin_b, role=_ensure_role(Role.HEAD_OF_INSTITUTE))
        school_b = School.objects.create(name='Test School CPB B', admin=admin_b)
        classroom_b = ClassRoom.objects.create(
            name='Class CPB B', school=school_b, code='CPB999',
        )
        student_b = CustomUser.objects.create_user(
            username='student_b_cpb', password='pass', email='student_b_cpb@test.com',
        )
        UserRole.objects.create(user=student_b, role=_ensure_role(Role.STUDENT))
        cs_b = ClassStudent.objects.create(classroom=classroom_b, student=student_b)

        client = Client()
        client.login(username='admin_cpb', password='pass')  # school A admin
        url = reverse('update_student_fee', kwargs={
            'class_id': classroom_b.id, 'student_id': student_b.id,
        })
        resp = client.post(url, {'fee_override': '50'})
        self.assertEqual(resp.status_code, 404)
        cs_b.refresh_from_db()
        self.assertIsNone(cs_b.fee_override)


class TestFeeVisibilityByRole(_ClassPageTestBase):
    """CPP-319: Only HoI and Accountant should see student fees on class detail."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hoi = CustomUser.objects.create_user(
            username='hoi_cpb', password='pass', email='hoi_cpb@test.com',
        )
        UserRole.objects.create(user=cls.hoi, role=_ensure_role(Role.HEAD_OF_INSTITUTE))
        cls.school.admin = cls.hoi
        cls.school.save()

        cls.hod = CustomUser.objects.create_user(
            username='hod_cpb', password='pass', email='hod_cpb@test.com',
        )
        UserRole.objects.create(user=cls.hod, role=_ensure_role(Role.HEAD_OF_DEPARTMENT))
        cls.dept.head = cls.hod
        cls.dept.save()

        cls.accountant = CustomUser.objects.create_user(
            username='acct_cpb', password='pass', email='acct_cpb@test.com',
        )
        UserRole.objects.create(user=cls.accountant, role=_ensure_role(Role.ACCOUNTANT))

    def _get_class_detail(self, username):
        client = Client()
        client.login(username=username, password='pass')
        return client.get(reverse('class_detail', kwargs={'class_id': self.classroom.id}))

    def test_hoi_can_see_fees(self):
        resp = self._get_class_detail('hoi_cpb')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['can_edit_fee'])

    def test_teacher_cannot_see_fees(self):
        resp = self._get_class_detail('teacher_cpb')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['can_edit_fee'])
        for item in resp.context['student_fee_data']:
            self.assertIsNone(item['effective_fee'])

    def test_hod_cannot_see_fees(self):
        resp = self._get_class_detail('hod_cpb')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['can_edit_fee'])
        for item in resp.context['student_fee_data']:
            self.assertIsNone(item['effective_fee'])

    def test_hod_cannot_update_student_fee(self):
        client = Client()
        client.login(username='hod_cpb', password='pass')
        url = reverse('update_student_fee', kwargs={
            'class_id': self.classroom.id, 'student_id': self.student.id,
        })
        resp = client.post(url, {'fee_override': '100'})
        self.assertIn(resp.status_code, [302, 403, 404])
        self.cs.refresh_from_db()
        self.assertIsNone(self.cs.fee_override)

    def test_teacher_cannot_update_student_fee(self):
        client = Client()
        client.login(username='teacher_cpb', password='pass')
        url = reverse('update_student_fee', kwargs={
            'class_id': self.classroom.id, 'student_id': self.student.id,
        })
        resp = client.post(url, {'fee_override': '100'})
        self.assertIn(resp.status_code, [302, 403, 404])
        self.cs.refresh_from_db()
        self.assertIsNone(self.cs.fee_override)
