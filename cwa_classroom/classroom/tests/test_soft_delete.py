"""
Tests for soft-delete (archive / deactivate / restore) functionality.

Covers:
- Classes: archive and restore via HoD/HoI views
- Departments: toggle active via HoI admin views
- Teachers: deactivate and restore via admin views
- Students: deactivate (with cascade to ClassStudent) and restore via admin views
- Permission checks: only authorised roles can archive/restore
- Default list views filter out inactive items
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    Subject, ClassTeacher, ClassStudent, DepartmentSubject,
    DepartmentTeacher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school(admin_role=Role.HEAD_OF_INSTITUTE):
    """Create admin + school + subscription.  Returns (user, school)."""
    user = CustomUser.objects.create_user(
        username='testhoi', password='pass12345', email='hoi@test.com',
    )
    _assign_role(user, admin_role)
    school = School.objects.create(name='Test School', slug='test-school', admin=user)
    plan = InstitutePlan.objects.create(
        name='Basic', slug='basic-sd', price=Decimal('89.00'),
        stripe_price_id='price_sd', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _setup_department(school, head=None):
    dept = Department.objects.create(
        school=school, name='Mathematics', slug='maths', head=head,
    )
    subj, _ = Subject.objects.get_or_create(
        slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
    )
    DepartmentSubject.objects.create(department=dept, subject=subj)
    if head:
        DepartmentTeacher.objects.create(department=dept, teacher=head)
        SchoolTeacher.objects.update_or_create(
            school=school, teacher=head,
            defaults={'role': 'head_of_department'},
        )
    return dept, subj


def _setup_teacher(school, dept=None, username='teacher1', email='teacher1@test.com'):
    teacher = CustomUser.objects.create_user(
        username=username, password='pass12345', email=email,
    )
    _assign_role(teacher, Role.TEACHER)
    st = SchoolTeacher.objects.update_or_create(school=school, teacher=teacher, defaults={'role': 'teacher'})
    if dept:
        DepartmentTeacher.objects.create(department=dept, teacher=teacher)
    return teacher, st


def _setup_student(school, username='student1', email='student1@test.com'):
    student = CustomUser.objects.create_user(
        username=username, password='pass12345', email=email,
    )
    _assign_role(student, Role.STUDENT)
    ss = SchoolStudent.objects.create(school=school, student=student)
    return student, ss


# ===========================================================================
# Class archive / restore tests
# ===========================================================================

class ClassArchiveRestoreTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()
        self.dept, _ = _setup_department(self.school, head=self.hoi)
        self.classroom = ClassRoom.objects.create(
            name='Year 5 Maths', school=self.school, department=self.dept,
        )
        self.client.login(username='testhoi', password='pass12345')

    def test_archive_class_sets_inactive(self):
        url = reverse('hod_delete_class', kwargs={'class_id': self.classroom.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertFalse(self.classroom.is_active)

    def test_restore_class_sets_active(self):
        self.classroom.is_active = False
        self.classroom.save()
        url = reverse('hod_restore_class', kwargs={'class_id': self.classroom.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertTrue(self.classroom.is_active)

    def test_archived_class_hidden_from_manage_classes(self):
        self.classroom.is_active = False
        self.classroom.save()
        url = reverse('hod_manage_classes')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # The active classes list should not contain our archived class
        active_classes = resp.context['classes']
        active_ids = [c.id for c in active_classes]
        self.assertNotIn(self.classroom.id, active_ids)

    def test_archived_class_in_deleted_classes(self):
        self.classroom.is_active = False
        self.classroom.save()
        url = reverse('hod_manage_classes')
        resp = self.client.get(url)
        deleted = resp.context['deleted_classes']
        deleted_ids = [c.id for c in deleted]
        self.assertIn(self.classroom.id, deleted_ids)

    def test_hod_only_cannot_restore_class(self):
        """An HoD (not HoI) should not see deleted classes to restore."""
        hod = CustomUser.objects.create_user(
            username='hod_only', password='pass12345', email='hod@test.com',
        )
        _assign_role(hod, Role.HEAD_OF_DEPARTMENT)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=hod, defaults={'role': 'head_of_department'})
        dept2 = Department.objects.create(
            school=self.school, name='Science', slug='science', head=hod,
        )
        DepartmentTeacher.objects.create(department=dept2, teacher=hod)

        self.classroom.is_active = False
        self.classroom.save()

        self.client.login(username='hod_only', password='pass12345')
        url = reverse('hod_manage_classes')
        resp = self.client.get(url)
        # HoD-only users should have empty deleted_classes
        self.assertEqual(list(resp.context['deleted_classes']), [])


# ===========================================================================
# Department archive / restore tests
# ===========================================================================

class DepartmentArchiveRestoreTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()
        self.dept, _ = _setup_department(self.school, head=self.hoi)
        self.client.login(username='testhoi', password='pass12345')

    def test_toggle_department_deactivates(self):
        url = reverse('admin_department_toggle_active', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertFalse(self.dept.is_active)

    def test_toggle_department_reactivates(self):
        self.dept.is_active = False
        self.dept.save()
        url = reverse('admin_department_toggle_active', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertTrue(self.dept.is_active)

    def test_inactive_department_hidden_by_default(self):
        self.dept.is_active = False
        self.dept.save()
        url = reverse('admin_school_departments', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        dept_names = [d['department'].name for d in resp.context['dept_data'].object_list]
        self.assertNotIn(self.dept.name, dept_names)

    def test_inactive_department_shown_with_toggle(self):
        self.dept.is_active = False
        self.dept.save()
        url = reverse('admin_school_departments', kwargs={'school_id': self.school.id})
        resp = self.client.get(url + '?show_inactive=1')
        self.assertEqual(resp.status_code, 200)
        dept_names = [d['department'].name for d in resp.context['dept_data'].object_list]
        self.assertIn(self.dept.name, dept_names)

    def test_only_hoi_can_toggle_department(self):
        """A regular teacher should not be able to toggle department active status."""
        teacher = CustomUser.objects.create_user(
            username='plain_teacher', password='pass12345', email='pt@test.com',
        )
        _assign_role(teacher, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=teacher, defaults={'role': 'teacher'})
        self.client.login(username='plain_teacher', password='pass12345')

        url = reverse('admin_department_toggle_active', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        # Should be redirected to home (permission denied)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertTrue(self.dept.is_active)  # Still active


# ===========================================================================
# Teacher deactivate / restore tests
# ===========================================================================

class TeacherDeactivateRestoreTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()
        self.teacher, self.st = _setup_teacher(self.school)
        self.client.login(username='testhoi', password='pass12345')

    def test_remove_teacher_deactivates(self):
        url = reverse('admin_school_teacher_remove', kwargs={
            'school_id': self.school.id, 'teacher_id': self.teacher.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.st.refresh_from_db()
        self.assertFalse(self.st.is_active)

    def test_restore_teacher_reactivates(self):
        self.st.is_active = False
        self.st.save()
        url = reverse('admin_school_teacher_restore', kwargs={
            'school_id': self.school.id, 'teacher_id': self.teacher.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.st.refresh_from_db()
        self.assertTrue(self.st.is_active)

    def test_inactive_teachers_hidden_by_default(self):
        self.st.is_active = False
        self.st.save()
        url = reverse('admin_school_teachers', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        teacher_ids = [s.teacher_id for s in resp.context['school_teachers'].object_list]
        self.assertNotIn(self.teacher.id, teacher_ids)

    def test_inactive_teachers_shown_with_toggle(self):
        self.st.is_active = False
        self.st.save()
        url = reverse('admin_school_teachers', kwargs={'school_id': self.school.id})
        resp = self.client.get(url + '?show_inactive=1')
        teacher_ids = [s.teacher_id for s in resp.context['school_teachers'].object_list]
        self.assertIn(self.teacher.id, teacher_ids)

    def test_regular_teacher_cannot_remove_teacher(self):
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('admin_school_teacher_remove', kwargs={
            'school_id': self.school.id, 'teacher_id': self.teacher.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.st.refresh_from_db()
        self.assertTrue(self.st.is_active)  # Still active

    def test_regular_teacher_cannot_restore_teacher(self):
        self.st.is_active = False
        self.st.save()
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('admin_school_teacher_restore', kwargs={
            'school_id': self.school.id, 'teacher_id': self.teacher.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.st.refresh_from_db()
        self.assertFalse(self.st.is_active)  # Still inactive


# ===========================================================================
# Student deactivate / restore / cascade tests
# ===========================================================================

class StudentDeactivateRestoreTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()
        self.dept, _ = _setup_department(self.school, head=self.hoi)
        self.student, self.ss = _setup_student(self.school)
        self.classroom = ClassRoom.objects.create(
            name='Year 5 Maths', school=self.school, department=self.dept,
        )
        self.cs = ClassStudent.objects.create(
            classroom=self.classroom, student=self.student,
        )
        self.client.login(username='testhoi', password='pass12345')

    def test_remove_student_deactivates(self):
        url = reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.ss.refresh_from_db()
        self.assertFalse(self.ss.is_active)

    def test_remove_student_cascades_to_class_student(self):
        """Deactivating a SchoolStudent should also deactivate their ClassStudent entries."""
        url = reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id,
        })
        self.client.post(url)
        self.cs.refresh_from_db()
        self.assertFalse(self.cs.is_active)

    def test_restore_student_reactivates(self):
        self.ss.is_active = False
        self.ss.save()
        self.cs.is_active = False
        self.cs.save()
        url = reverse('admin_school_student_restore', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.ss.refresh_from_db()
        self.assertTrue(self.ss.is_active)

    def test_restore_student_cascades_to_class_student(self):
        """Restoring a SchoolStudent should also restore their ClassStudent entries."""
        self.ss.is_active = False
        self.ss.save()
        self.cs.is_active = False
        self.cs.save()
        url = reverse('admin_school_student_restore', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id,
        })
        self.client.post(url)
        self.cs.refresh_from_db()
        self.assertTrue(self.cs.is_active)

    def test_inactive_students_hidden_by_default(self):
        self.ss.is_active = False
        self.ss.save()
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        student_ids = [s.student_id for s in resp.context['school_students'].object_list]
        self.assertNotIn(self.student.id, student_ids)

    def test_inactive_students_shown_with_toggle(self):
        self.ss.is_active = False
        self.ss.save()
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        resp = self.client.get(url + '?show_inactive=1')
        student_ids = [s.student_id for s in resp.context['school_students'].object_list]
        self.assertIn(self.student.id, student_ids)

    def test_cascade_only_affects_same_school(self):
        """ClassStudent entries at a different school should not be affected."""
        other_school = School.objects.create(name='Other School', slug='other-school', admin=self.hoi)
        other_classroom = ClassRoom.objects.create(
            name='Other Class', school=other_school,
        )
        other_cs = ClassStudent.objects.create(
            classroom=other_classroom, student=self.student,
        )
        url = reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id,
        })
        self.client.post(url)
        other_cs.refresh_from_db()
        self.assertTrue(other_cs.is_active)  # Not affected


# ===========================================================================
# Subject is_active field test
# ===========================================================================

class SubjectIsActiveTests(TestCase):
    def test_subject_has_is_active_field(self):
        """Verify Subject model has is_active field and defaults to True."""
        subj = Subject.objects.create(name='Test Subject', slug='test-subject')
        self.assertTrue(subj.is_active)
        subj.is_active = False
        subj.save()
        subj.refresh_from_db()
        self.assertFalse(subj.is_active)
