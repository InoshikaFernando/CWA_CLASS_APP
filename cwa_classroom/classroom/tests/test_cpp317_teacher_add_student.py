"""
Unit tests for CPP-317: Teacher can add a new student to a class,
with optional card number pre-assignment. Card number can also be
entered by the student on first login (CompleteProfileView).

Covers:
  TeacherAddStudentToClassView (GET + POST)
  1.  Teacher GET shows add-student form
  2.  Teacher POST creates student + enrols in class
  3.  Teacher POST with card_number pre-claims StudentCard
  4.  Teacher POST with duplicate email returns form error
  5.  Teacher POST with invalid card number returns form error
  6.  Teacher POST with already-claimed card returns form error
  7.  Teacher POST blocked for class they don't teach (404)
  8.  Student role DENIED (redirect)
  9.  Parent role DENIED (redirect)
  10. HoD can add student to class in their department
  11. HoI can add student to any class in their school

  CompleteProfileView card number path
  12. Student enters valid card number → activated without payment
  13. Student with pre-claimed card sees banner on GET
  14. Student enters wrong card number → error
  15. Student enters card number for wrong school → error
  16. Card claimed by another student → error
  17. Non-school student cannot use card number path
"""

import uuid

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, SchoolTeacher,
    ClassRoom, ClassStudent, Department, StudentCard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role_name, suffix=None, **kwargs):
    uid = suffix or uuid.uuid4().hex[:8]
    u = CustomUser.objects.create_user(
        username=f'{role_name}_{uid}',
        email=f'{role_name}_{uid}@test.com',
        password='testpass123',
        **kwargs,
    )
    role, _ = Role.objects.get_or_create(
        name=role_name, defaults={'display_name': role_name.title()}
    )
    UserRole.objects.create(user=u, role=role, assigned_by=u)
    return u


def _make_school(admin):
    return School.objects.create(
        name=f'School {uuid.uuid4().hex[:6]}',
        admin=admin,
    )


def _make_class(school):
    return ClassRoom.objects.create(
        name=f'Class {uuid.uuid4().hex[:6]}',
        school=school,
    )


# ---------------------------------------------------------------------------
# Tests: TeacherAddStudentToClassView
# ---------------------------------------------------------------------------

class TeacherAddStudentGetTest(TestCase):
    def setUp(self):
        self.hoi = _make_user(Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.teacher = _make_user(Role.TEACHER)
        SchoolTeacher.objects.create(school=self.school, teacher=self.teacher)
        self.classroom = _make_class(self.school)
        self.classroom.teachers.add(self.teacher)
        self.client = Client()

    def test_get_shows_form(self):
        self.client.force_login(self.teacher)
        url = reverse('teacher_add_student_to_class', kwargs={'class_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add New Student')
        self.assertContains(resp, self.classroom.name)

    def test_student_role_denied(self):
        student = _make_user(Role.STUDENT)
        self.client.force_login(student)
        url = reverse('teacher_add_student_to_class', kwargs={'class_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_parent_role_denied(self):
        parent = _make_user(Role.PARENT)
        self.client.force_login(parent)
        url = reverse('teacher_add_student_to_class', kwargs={'class_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_teacher_404_for_foreign_class(self):
        other_hoi = _make_user(Role.HEAD_OF_INSTITUTE, suffix='oth')
        other_school = _make_school(other_hoi)
        other_class = _make_class(other_school)
        self.client.force_login(self.teacher)
        url = reverse('teacher_add_student_to_class', kwargs={'class_id': other_class.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)


class TeacherAddStudentPostTest(TestCase):
    def setUp(self):
        self.hoi = _make_user(Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.teacher = _make_user(Role.TEACHER)
        SchoolTeacher.objects.create(school=self.school, teacher=self.teacher)
        self.classroom = _make_class(self.school)
        self.classroom.teachers.add(self.teacher)
        self.url = reverse('teacher_add_student_to_class', kwargs={'class_id': self.classroom.id})
        self.client = Client()
        self.client.force_login(self.teacher)

    def _post(self, **overrides):
        data = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': f'jane_{uuid.uuid4().hex[:6]}@test.com',
            'password': 'TempPass123',
            'username': '',
            'card_number': '',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_creates_student_and_enrols(self):
        email = f'new_{uuid.uuid4().hex[:6]}@test.com'
        resp = self._post(email=email)
        self.assertRedirects(resp, reverse('class_detail', kwargs={'class_id': self.classroom.id}))
        user = CustomUser.objects.get(email=email)
        self.assertTrue(user.has_role(Role.STUDENT))
        self.assertTrue(user.must_change_password)
        self.assertFalse(user.profile_completed)
        self.assertTrue(SchoolStudent.objects.filter(school=self.school, student=user).exists())
        self.assertTrue(ClassStudent.objects.filter(classroom=self.classroom, student=user, is_active=True).exists())

    def test_post_with_card_number_preclaims_card(self):
        card = StudentCard.objects.create(
            school=self.school, card_number='CARD-001',
        )
        email = f'card_{uuid.uuid4().hex[:6]}@test.com'
        resp = self._post(email=email, card_number='CARD-001')
        self.assertRedirects(resp, reverse('class_detail', kwargs={'class_id': self.classroom.id}))
        card.refresh_from_db()
        user = CustomUser.objects.get(email=email)
        self.assertEqual(card.student, user)
        self.assertTrue(card.is_claimed)
        self.assertIsNotNone(card.claimed_at)

    def test_duplicate_email_returns_form_error(self):
        existing = _make_user(Role.STUDENT)
        resp = self._post(email=existing.email)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')
        # No new user created
        self.assertEqual(CustomUser.objects.filter(email=existing.email).count(), 1)

    def test_invalid_card_number_returns_form_error(self):
        resp = self._post(card_number='NONEXISTENT')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Card number not found')

    def test_already_claimed_card_returns_form_error(self):
        owner = _make_user(Role.STUDENT, suffix='own')
        card = StudentCard.objects.create(
            school=self.school,
            card_number='TAKEN-001',
            student=owner,
            is_claimed=True,
        )
        resp = self._post(card_number=card.card_number)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already been claimed')

    def test_hod_can_add_student(self):
        hod = _make_user(Role.HEAD_OF_DEPARTMENT)
        dept = Department.objects.create(school=self.school, name='Dept', head=hod)
        self.classroom.department = dept
        self.classroom.save()
        self.client.force_login(hod)
        email = f'hod_{uuid.uuid4().hex[:6]}@test.com'
        resp = self._post(email=email)
        self.assertRedirects(resp, reverse('class_detail', kwargs={'class_id': self.classroom.id}))

    def test_hoi_can_add_student(self):
        self.client.force_login(self.hoi)
        email = f'hoi_{uuid.uuid4().hex[:6]}@test.com'
        resp = self._post(email=email)
        self.assertRedirects(resp, reverse('class_detail', kwargs={'class_id': self.classroom.id}))


# ---------------------------------------------------------------------------
# Tests: CompleteProfileView card number path
# ---------------------------------------------------------------------------

class CompleteProfileCardNumberTest(TestCase):
    def setUp(self):
        self.hoi = _make_user(Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.client = Client()
        self.url = reverse('complete_profile')

    def _make_student(self):
        s = _make_user(Role.STUDENT)
        s.must_change_password = True
        s.profile_completed = False
        s.save()
        SchoolStudent.objects.create(school=self.school, student=s)
        return s

    def _post_profile(self, student, extra=None):
        data = {
            'first_name': 'Test',
            'last_name': 'Student',
            'new_password': 'NewPass456',
            'confirm_password': 'NewPass456',
            'country': 'NZ',
            'region': '',
            'phone': '',
            'street_address': '',
            'city': '',
            'postal_code': '',
            'discount_code': '',
            'card_number': '',
        }
        if extra:
            data.update(extra)
        self.client.force_login(student)
        return self.client.post(self.url, data)

    def test_valid_card_activates_student(self):
        student = self._make_student()
        card = StudentCard.objects.create(school=self.school, card_number='ACT-001')
        resp = self._post_profile(student, {'card_number': 'ACT-001'})
        self.assertRedirects(resp, reverse('subjects_hub'), fetch_redirect_response=False)
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)
        card.refresh_from_db()
        self.assertEqual(card.student, student)
        self.assertTrue(card.is_claimed)

    def test_get_shows_pre_claimed_card_banner(self):
        student = self._make_student()
        card = StudentCard.objects.create(
            school=self.school, card_number='PRE-001',
            student=student, is_claimed=True,
        )
        self.client.force_login(student)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'PRE-001')
        self.assertContains(resp, 'pre-assigned')

    def test_wrong_card_number_returns_error(self):
        student = self._make_student()
        resp = self._post_profile(student, {'card_number': 'BADCARD'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'not found')
        student.refresh_from_db()
        self.assertFalse(student.profile_completed)

    def test_card_for_wrong_school_returns_error(self):
        student = self._make_student()
        other_hoi = _make_user(Role.HEAD_OF_INSTITUTE, suffix='oth2')
        other_school = _make_school(other_hoi)
        StudentCard.objects.create(school=other_school, card_number='OTHER-001')
        resp = self._post_profile(student, {'card_number': 'OTHER-001'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'not found')

    def test_claimed_by_other_student_returns_error(self):
        student = self._make_student()
        other = _make_user(Role.STUDENT, suffix='oth3')
        card = StudentCard.objects.create(
            school=self.school, card_number='OTH-001',
            student=other, is_claimed=True,
        )
        resp = self._post_profile(student, {'card_number': card.card_number})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already been claimed')

    def test_non_school_student_cannot_use_card(self):
        student = _make_user(Role.STUDENT, suffix='noss')
        student.must_change_password = True
        student.profile_completed = False
        student.save()
        # No SchoolStudent record → not a school student
        card = StudentCard.objects.create(school=self.school, card_number='FREE-001')
        resp = self._post_profile(student, {'card_number': card.card_number})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'school students')

    def test_pre_assigned_card_activates_without_card_number(self):
        """A teacher-pre-assigned card (is_claimed + student=self) must activate
        the student on profile completion even though the form submits no
        card_number — the banner branch hides that input."""
        student = self._make_student()
        card = StudentCard.objects.create(
            school=self.school, card_number='PRE-002',
            student=student, is_claimed=True,
        )
        # card_number deliberately left blank (default in _post_profile)
        resp = self._post_profile(student)
        self.assertRedirects(resp, reverse('subjects_hub'), fetch_redirect_response=False)
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)
        card.refresh_from_db()
        self.assertTrue(card.is_claimed)
        self.assertEqual(card.student, student)

    def test_card_number_match_is_case_insensitive(self):
        student = self._make_student()
        card = StudentCard.objects.create(school=self.school, card_number='ACT-009')
        resp = self._post_profile(student, {'card_number': 'act-009'})
        self.assertRedirects(resp, reverse('subjects_hub'), fetch_redirect_response=False)
        student.refresh_from_db()
        self.assertTrue(student.profile_completed)
        card.refresh_from_db()
        self.assertTrue(card.is_claimed)
