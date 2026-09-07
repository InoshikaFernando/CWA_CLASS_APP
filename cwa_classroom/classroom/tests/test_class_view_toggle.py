"""
Tests for the list / grid view toggle on class-listing pages.

The toggle is a shared partial (``partials/view_toggle.html``) wired into the
student "My Classes", teacher dashboard, HoD "Manage Classes" and parent
"Classes" pages. It renders a segmented control plus a container that switches
between a tile grid (``cwa-grid``) and a single column of rows (``cwa-list``),
remembering the choice in ``localStorage``.

These tests assert the toggle markup is present (and correctly parameterised)
on each page when at least one class is listed.
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    Subject, ClassTeacher, ClassStudent, DepartmentSubject, DepartmentTeacher,
    ParentStudent,
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


def _setup_school():
    hoi = CustomUser.objects.create_user(
        username='vt_hoi', password='password1!', email='wlhtestmails+vt_hoi@gmail.com',
    )
    _assign_role(hoi, Role.HEAD_OF_INSTITUTE)
    school = School.objects.create(name='Toggle School', slug='toggle-school', admin=hoi)
    plan = InstitutePlan.objects.create(
        name='Basic', slug='basic-vt', price=Decimal('89.00'),
        stripe_price_id='price_vt', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return hoi, school


class ClassViewToggleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()

        self.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
        )
        self.dept = Department.objects.create(
            school=self.school, name='Mathematics', slug='maths', head=self.hoi,
        )
        DepartmentSubject.objects.create(department=self.dept, subject=self.subject)
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.hoi)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.hoi,
            defaults={'role': 'head_of_department'},
        )

        # A teacher who owns a class.
        self.teacher = CustomUser.objects.create_user(
            username='vt_teacher', password='password1!',
            email='wlhtestmails+vt_teacher@gmail.com',
        )
        _assign_role(self.teacher, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.teacher, defaults={'role': 'teacher'},
        )
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.teacher)

        self.classroom = ClassRoom.objects.create(
            name='Year 5 Maths', school=self.school, department=self.dept,
            subject=self.subject,
        )
        ClassTeacher.objects.create(classroom=self.classroom, teacher=self.teacher)

        # A student enrolled in the class.
        self.student = CustomUser.objects.create_user(
            username='vt_student', password='password1!',
            email='wlhtestmails+vt_student@gmail.com',
        )
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)

    def _assert_toggle(self, resp, container_id):
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('data-view-toggle="%s"' % container_id, html)
        self.assertIn('data-view-btn="grid"', html)
        self.assertIn('data-view-btn="list"', html)
        # Container carries the marker attribute the toggle script targets.
        self.assertIn('id="%s"' % container_id, html)
        self.assertIn('data-cwa-container', html)

    def test_hod_manage_classes_has_toggle(self):
        self.client.login(username='vt_hoi', password='password1!')
        resp = self.client.get(reverse('hod_manage_classes'))
        self._assert_toggle(resp, 'hod-classes')

    def test_teacher_dashboard_has_toggle(self):
        self.client.login(username='vt_teacher', password='password1!')
        resp = self.client.get(reverse('teacher_dashboard'))
        self._assert_toggle(resp, 'teacher-classes')

    def test_student_my_classes_has_toggle(self):
        self.client.login(username='vt_student', password='password1!')
        resp = self.client.get(reverse('student_my_classes'))
        self._assert_toggle(resp, 'student-classes')

    def test_parent_classes_has_toggle(self):
        parent = CustomUser.objects.create_user(
            username='vt_parent', password='password1!',
            email='wlhtestmails+vt_parent@gmail.com',
        )
        _assign_role(parent, Role.PARENT)
        ParentStudent.objects.create(
            parent=parent, student=self.student, school=self.school,
        )
        self.client.login(username='vt_parent', password='password1!')
        resp = self.client.get(reverse('parent_classes'))
        self._assert_toggle(resp, 'parent-classes')
