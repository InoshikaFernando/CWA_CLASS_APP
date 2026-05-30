"""
Unit tests for CPP-305: Teacher-level password reset from class detail page.

Covers:
1. Teacher can GET reset-password modal for own student
2. Teacher can POST reset for own student (random mode)
3. Senior teacher can reset password for own student
4. HoD can reset password for student in their department's class
5. Teacher DENIED (404) for student not in their classes
6. Student role DENIED (302 redirect via RoleRequiredMixin)
7. Parent role DENIED (302 redirect via RoleRequiredMixin)
8. Admin/HoI still works (unchanged)
9. `next` redirect parameter honoured on POST
10. Open redirect blocked
"""
import uuid
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, SchoolTeacher,
    ClassRoom, ClassTeacher, ClassStudent, Department,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:6]


def _make_user(prefix, role_name):
    username = f'{prefix}_{_uid()}'
    user = CustomUser.objects.create_user(
        username=username,
        email=f'{username}@test.local',
        password='testpass123',
        first_name=prefix.capitalize(),
        last_name='Test',
    )
    role, _ = Role.objects.get_or_create(name=role_name, defaults={'display_name': role_name.title()})
    UserRole.objects.create(user=user, role=role)
    return user


def _make_school(admin_user):
    uid = _uid()
    return School.objects.create(
        name=f'School305 {uid}',
        slug=f'school305-{uid}',
        admin=admin_user,
        is_active=True,
        is_published=True,
    )


def _make_classroom(school, teacher, name=None):
    name = name or f'Math305 {_uid()}'
    classroom = ClassRoom.objects.create(
        name=name,
        code=_uid(),
        school=school,
    )
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)
    return classroom


def _enroll_student(school, classroom, student):
    SchoolStudent.objects.get_or_create(school=school, student=student, defaults={'is_active': True})
    ClassStudent.objects.get_or_create(classroom=classroom, student=student, defaults={'is_active': True})


def _modal_url(school_id, user_id):
    return reverse('admin_user_password_reset_modal', args=[school_id, user_id])


def _reset_url(school_id, user_id):
    return reverse('admin_user_password_reset', args=[school_id, user_id])


# ---------------------------------------------------------------------------
# Base setup
# ---------------------------------------------------------------------------

class CPP305Base(TestCase):
    def setUp(self):
        self.hoi = _make_user('hoi305', Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        # hoi is school admin, so _get_user_school_or_404 finds it via admin FK

        self.teacher = _make_user('teacher305', Role.TEACHER)
        SchoolTeacher.objects.get_or_create(
            school=self.school, teacher=self.teacher,
            defaults={'role': 'teacher', 'is_active': True},
        )

        self.student = _make_user('student305', Role.STUDENT)
        self.classroom = _make_classroom(self.school, self.teacher)
        _enroll_student(self.school, self.classroom, self.student)

        self.other_student = _make_user('otherstudent305', Role.STUDENT)
        # other_student is NOT enrolled in teacher's class

        self.client = Client()


# ---------------------------------------------------------------------------
# Tests: teacher can GET modal for own student
# ---------------------------------------------------------------------------

class TeacherModalGetTest(CPP305Base):
    def test_teacher_can_get_modal_for_own_student(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(_modal_url(self.school.id, self.student.id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Reset Password')
        self.assertContains(resp, self.student.username)

    def test_teacher_denied_modal_for_other_student(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(_modal_url(self.school.id, self.other_student.id))
        self.assertEqual(resp.status_code, 404)

    def test_modal_includes_next_url(self):
        self.client.force_login(self.teacher)
        class_url = reverse('class_detail', args=[self.classroom.id])
        resp = self.client.get(
            _modal_url(self.school.id, self.student.id),
            {'next': class_url},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'value="{class_url}"')


# ---------------------------------------------------------------------------
# Tests: teacher can POST reset for own student
# ---------------------------------------------------------------------------

class TeacherPasswordResetPostTest(CPP305Base):
    def _post_reset(self, school_id, user_id, mode='random', extra=None):
        data = {'mode': mode}
        if extra:
            data.update(extra)
        return self.client.post(_reset_url(school_id, user_id), data)

    def test_teacher_can_reset_own_student_random(self):
        self.client.force_login(self.teacher)
        resp = self._post_reset(self.school.id, self.student.id)
        # Success → redirect to admin_school_students (student role_label)
        self.assertEqual(resp.status_code, 302)

    def test_teacher_denied_reset_for_other_student(self):
        self.client.force_login(self.teacher)
        resp = self._post_reset(self.school.id, self.other_student.id)
        self.assertEqual(resp.status_code, 404)

    def test_next_redirect_honoured(self):
        self.client.force_login(self.teacher)
        class_url = reverse('class_detail', args=[self.classroom.id])
        resp = self.client.post(
            _reset_url(self.school.id, self.student.id),
            {'mode': 'random', 'next': class_url},
        )
        self.assertRedirects(resp, class_url, fetch_redirect_response=False)

    def test_next_redirect_open_redirect_blocked(self):
        self.client.force_login(self.teacher)
        resp = self.client.post(
            _reset_url(self.school.id, self.student.id),
            {'mode': 'random', 'next': 'https://evil.com/'},
        )
        # Should NOT redirect to external URL — falls back to role-based URL
        self.assertNotEqual(resp.get('Location', ''), 'https://evil.com/')


# ---------------------------------------------------------------------------
# Tests: senior teacher and HoD
# ---------------------------------------------------------------------------

class SeniorTeacherAndHoDTest(CPP305Base):
    def setUp(self):
        super().setUp()
        self.senior = _make_user('senior305', Role.SENIOR_TEACHER)
        SchoolTeacher.objects.get_or_create(
            school=self.school, teacher=self.senior,
            defaults={'role': 'senior_teacher', 'is_active': True},
        )
        self.senior_classroom = _make_classroom(self.school, self.senior)
        self.senior_student = _make_user('senstu305', Role.STUDENT)
        _enroll_student(self.school, self.senior_classroom, self.senior_student)

        self.hod = _make_user('hod305', Role.HEAD_OF_DEPARTMENT)
        SchoolTeacher.objects.get_or_create(
            school=self.school, teacher=self.hod,
            defaults={'role': 'head_of_department', 'is_active': True},
        )
        uid = _uid()
        self.department = Department.objects.create(
            school=self.school, name=f'Science Dept {uid}', slug=f'science-dept-{uid}', head=self.hod,
        )
        self.hod_classroom = _make_classroom(self.school, self.hod)
        self.hod_classroom.department = self.department
        self.hod_classroom.save()
        self.dept_student = _make_user('deptstu305', Role.STUDENT)
        _enroll_student(self.school, self.hod_classroom, self.dept_student)

    def test_senior_teacher_can_get_modal_for_own_student(self):
        self.client.force_login(self.senior)
        resp = self.client.get(_modal_url(self.school.id, self.senior_student.id))
        self.assertEqual(resp.status_code, 200)

    def test_senior_teacher_denied_for_other_student(self):
        self.client.force_login(self.senior)
        resp = self.client.get(_modal_url(self.school.id, self.student.id))
        self.assertEqual(resp.status_code, 404)

    def test_hod_can_reset_via_dept_class(self):
        self.client.force_login(self.hod)
        resp = self.client.get(_modal_url(self.school.id, self.dept_student.id))
        self.assertEqual(resp.status_code, 200)

    def test_hod_denied_for_student_outside_dept(self):
        self.client.force_login(self.hod)
        resp = self.client.get(_modal_url(self.school.id, self.student.id))
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Tests: roles that cannot reset
# ---------------------------------------------------------------------------

class UnauthorisedRolesTest(CPP305Base):
    def test_student_role_denied(self):
        student_user = _make_user('stuactor305', Role.STUDENT)
        self.client.force_login(student_user)
        resp = self.client.get(_modal_url(self.school.id, self.student.id))
        # RoleRequiredMixin redirects (302) for wrong role, not 403
        self.assertEqual(resp.status_code, 302)

    def test_parent_role_denied(self):
        parent = _make_user('parent305', Role.PARENT)
        self.client.force_login(parent)
        resp = self.client.get(_modal_url(self.school.id, self.student.id))
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# Tests: admin/HoI path unchanged
# ---------------------------------------------------------------------------

class AdminHoiResetTest(CPP305Base):
    def test_hoi_can_reset_any_school_student(self):
        self.client.force_login(self.hoi)
        resp = self.client.get(_modal_url(self.school.id, self.student.id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Reset Password')

    def test_hoi_can_reset_student_not_in_teacher_class(self):
        SchoolStudent.objects.get_or_create(
            school=self.school, student=self.other_student, defaults={'is_active': True},
        )
        self.client.force_login(self.hoi)
        resp = self.client.get(_modal_url(self.school.id, self.other_student.id))
        self.assertEqual(resp.status_code, 200)
