"""
Tests for HoD cross-department class visibility.

Regression tests for:
- ClassDetailView: HoD can view classes they teach outside their department
- HoDManageClassesView: department filter, visibility rules
  (all classes in headed dept, only own classes in other depts)
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, Department, DepartmentTeacher, ClassRoom, ClassTeacher,
    SchoolTeacher,
)


class HoDCrossDepartmentTestBase(TestCase):
    """
    Fixture: Inoshi is HoD of Maths. She also teaches Coding classes.
    Another teacher (Bob) teaches Coding classes too.
    """

    def setUp(self):
        # Roles
        self.hod_role, _ = Role.objects.get_or_create(
            name='head_of_department',
            defaults={'display_name': 'Head of Department'},
        )
        self.teacher_role, _ = Role.objects.get_or_create(
            name='teacher',
            defaults={'display_name': 'Teacher'},
        )

        # Users
        self.inoshi = CustomUser.objects.create_user(
            username='inoshi', email='wlhtestmails+inoshi@gmail.com', password='password1!',
        )
        UserRole.objects.create(user=self.inoshi, role=self.hod_role)
        UserRole.objects.create(user=self.inoshi, role=self.teacher_role)

        self.bob = CustomUser.objects.create_user(
            username='bob', email='wlhtestmails+bob@gmail.com', password='password1!',
        )
        UserRole.objects.create(user=self.bob, role=self.teacher_role)

        # School — use a separate admin so Inoshi doesn't get auto-promoted to HoI
        self.school_admin = CustomUser.objects.create_user(
            username='schooladmin', email='wlhtestmails+schooladmin@gmail.com', password='password1!',
        )
        self.school = School.objects.create(
            name='Test School', slug='test-school-hod', admin=self.school_admin,
        )
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.inoshi,
            defaults={'is_active': True, 'role': 'head_of_department'},
        )
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.bob, is_active=True,
        )

        # Maths department — Inoshi is HoD
        self.maths_dept = Department.objects.create(
            name='Mathematics', slug='maths', school=self.school,
            head=self.inoshi, is_active=True,
        )
        DepartmentTeacher.objects.create(
            department=self.maths_dept, teacher=self.inoshi,
        )

        # Coding department — Inoshi is just a teacher
        self.coding_dept = Department.objects.create(
            name='Coding', slug='coding', school=self.school,
            is_active=True,
        )
        DepartmentTeacher.objects.create(
            department=self.coding_dept, teacher=self.inoshi,
        )
        DepartmentTeacher.objects.create(
            department=self.coding_dept, teacher=self.bob,
        )

        # Maths classes — Inoshi teaches Maths 01, Bob teaches Maths 02
        self.maths_01 = ClassRoom.objects.create(
            name='Maths 01', school=self.school,
            department=self.maths_dept, is_active=True,
        )
        self.maths_01.teachers.add(self.inoshi)

        self.maths_02 = ClassRoom.objects.create(
            name='Maths 02', school=self.school,
            department=self.maths_dept, is_active=True,
        )
        self.maths_02.teachers.add(self.bob)

        # Coding classes — Inoshi teaches Coding 01, Bob teaches Coding 02
        self.coding_01 = ClassRoom.objects.create(
            name='Coding 01', school=self.school,
            department=self.coding_dept, is_active=True,
        )
        self.coding_01.teachers.add(self.inoshi)

        self.coding_02 = ClassRoom.objects.create(
            name='Coding 02', school=self.school,
            department=self.coding_dept, is_active=True,
        )
        self.coding_02.teachers.add(self.bob)

        self.client.login(username='inoshi', password='password1!')


class ClassDetailViewHoDTest(HoDCrossDepartmentTestBase):
    """ClassDetailView: HoD can view classes they teach outside their department."""

    def test_hod_can_view_own_department_class(self):
        """Inoshi can view Maths 01 (her department, her class)."""
        resp = self.client.get(reverse('class_detail', args=[self.maths_01.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_view_other_teacher_class_in_own_department(self):
        """Inoshi can view Maths 02 (her department, Bob's class) — she's HoD."""
        resp = self.client.get(reverse('class_detail', args=[self.maths_02.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_view_class_she_teaches_in_other_department(self):
        """Inoshi can view Coding 01 (other department, but she teaches it)."""
        resp = self.client.get(reverse('class_detail', args=[self.coding_01.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hod_cannot_view_class_she_doesnt_teach_in_other_department(self):
        """Inoshi cannot view Coding 02 (other department, Bob's class)."""
        resp = self.client.get(reverse('class_detail', args=[self.coding_02.id]))
        self.assertEqual(resp.status_code, 404)


class HoDManageClassesViewFilterTest(HoDCrossDepartmentTestBase):
    """HoDManageClassesView: department filter and visibility rules."""

    def test_all_departments_shows_correct_classes(self):
        """No filter: Maths 01, Maths 02 (headed dept), Coding 01 (teaches)."""
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertEqual(resp.status_code, 200)
        classes = list(resp.context['classes'])
        class_names = {c.name for c in classes}
        # Headed dept: all maths classes
        self.assertIn('Maths 01', class_names)
        self.assertIn('Maths 02', class_names)
        # Other dept: only classes she teaches
        self.assertIn('Coding 01', class_names)
        # Should NOT include Bob's coding class
        self.assertNotIn('Coding 02', class_names)

    def test_filter_by_headed_department_shows_all_classes(self):
        """Filter by Maths: shows all maths classes (Inoshi is HoD)."""
        resp = self.client.get(
            reverse('hod_manage_classes') + f'?department={self.maths_dept.id}'
        )
        self.assertEqual(resp.status_code, 200)
        classes = list(resp.context['classes'])
        class_names = {c.name for c in classes}
        self.assertIn('Maths 01', class_names)
        self.assertIn('Maths 02', class_names)
        self.assertNotIn('Coding 01', class_names)

    def test_filter_by_teaching_department_shows_only_own_classes(self):
        """Filter by Coding: shows only Coding 01 (Inoshi teaches it), not Coding 02."""
        resp = self.client.get(
            reverse('hod_manage_classes') + f'?department={self.coding_dept.id}'
        )
        self.assertEqual(resp.status_code, 200)
        classes = list(resp.context['classes'])
        class_names = {c.name for c in classes}
        self.assertIn('Coding 01', class_names)
        self.assertNotIn('Coding 02', class_names)

    def test_department_dropdown_shows_both_departments(self):
        """Dropdown should list both Maths and Coding departments."""
        resp = self.client.get(reverse('hod_manage_classes'))
        departments = list(resp.context['departments'])
        dept_names = {d.name for d in departments}
        self.assertIn('Mathematics', dept_names)
        self.assertIn('Coding', dept_names)

    def test_selected_dept_id_in_context(self):
        """selected_dept_id should be set when filtering."""
        resp = self.client.get(
            reverse('hod_manage_classes') + f'?department={self.maths_dept.id}'
        )
        self.assertEqual(resp.context['selected_dept_id'], self.maths_dept.id)

    def test_no_filter_selected_dept_id_is_none(self):
        """selected_dept_id should be None when no filter applied."""
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertIsNone(resp.context['selected_dept_id'])

    def test_invalid_department_id_shows_all(self):
        """Invalid department ID falls back to showing all."""
        resp = self.client.get(
            reverse('hod_manage_classes') + '?department=99999'
        )
        self.assertEqual(resp.status_code, 200)
        classes = list(resp.context['classes'])
        # Should fall back to all visible classes
        self.assertTrue(len(classes) >= 3)
