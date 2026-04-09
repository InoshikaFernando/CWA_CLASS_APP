"""
Tests for classroom/views_department.py to increase coverage from ~35% to 70%+.
Covers all department CRUD views, HoD assignment, teacher management,
class assignment, fee updates, toggle active, delete, and level management.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, DepartmentSubject, DepartmentTeacher,
    DepartmentLevel, ClassRoom, SchoolTeacher, Subject, Level,
)


def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


class DepartmentViewsTestBase(TestCase):
    """Shared setup for all department view tests."""

    def setUp(self):
        self.hoi = CustomUser.objects.create_user(
            username='hoi_dept', password='password1!', email='wlhtestmails+hoi@gmail.com',
        )
        UserRole.objects.create(user=self.hoi, role=_create_role(Role.HEAD_OF_INSTITUTE))
        self.school = School.objects.create(
            name='Dept School', slug='dept-school', admin=self.hoi,
        )
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-dept', price=Decimal('89'),
            stripe_price_id='p', class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')
        self.subject = Subject.objects.create(name='Maths', slug='maths')
        self.dept = Department.objects.create(
            school=self.school, name='Mathematics', slug='mathematics',
        )
        DepartmentSubject.objects.create(department=self.dept, subject=self.subject)
        self.client.login(username='hoi_dept', password='password1!')


# ---------------------------------------------------------------------------
# DepartmentListView
# ---------------------------------------------------------------------------
class DepartmentListViewTests(DepartmentViewsTestBase):

    def test_list_departments_get(self):
        url = reverse('admin_school_departments', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('dept_data', resp.context)
        self.assertEqual(resp.context['total_departments'], 1)

    def test_list_departments_with_teachers_and_classes(self):
        teacher = CustomUser.objects.create_user(
            username='t1', password='password1!', email='wlhtestmails+t1@gmail.com',
        )
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=teacher)
        DepartmentTeacher.objects.create(department=self.dept, teacher=teacher)
        ClassRoom.objects.create(
            name='Class A', school=self.school, department=self.dept,
        )
        url = reverse('admin_school_departments', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        self.assertEqual(resp.context['total_teachers'], 1)
        self.assertEqual(resp.context['total_classes'], 1)

    def test_list_departments_requires_login(self):
        self.client.logout()
        url = reverse('admin_school_departments', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# DepartmentCreateView
# ---------------------------------------------------------------------------
class DepartmentCreateViewTests(DepartmentViewsTestBase):

    def test_create_get(self):
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('subjects', resp.context)

    def test_create_post_success(self):
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {
            'name': 'Science',
            'description': 'Science department',
            'subjects': [str(self.subject.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Department.objects.filter(school=self.school, name='Science').exists())

    def test_create_post_empty_name(self):
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {'name': '', 'description': ''})
        self.assertEqual(resp.status_code, 200)  # re-renders form
        self.assertIn('form_data', resp.context)

    def test_create_post_with_new_subject(self):
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {
            'name': 'Arts',
            'description': '',
            'subjects': ['new'],
            'new_subject_name': 'Visual Arts',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(name='Visual Arts', school=self.school).exists())

    def test_create_post_no_subjects(self):
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {'name': 'Empty Dept', 'description': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Department.objects.filter(name='Empty Dept').exists())

    def test_create_duplicate_slug_increments(self):
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        self.client.post(url, {'name': 'Mathematics'})
        # Second one should get slug 'mathematics-1'
        dept2 = Department.objects.filter(school=self.school, name='Mathematics').exclude(
            id=self.dept.id,
        ).first()
        self.assertIsNotNone(dept2)
        self.assertNotEqual(dept2.slug, self.dept.slug)

    def test_create_with_global_levels_auto_mapped(self):
        """When a subject has global levels, they auto-map to the new department."""
        level = Level.objects.create(
            level_number=1, display_name='Year 1', subject=self.subject,
        )
        url = reverse('admin_department_create', kwargs={'school_id': self.school.id})
        self.client.post(url, {
            'name': 'Auto Levels Dept',
            'subjects': [str(self.subject.id)],
        })
        new_dept = Department.objects.get(name='Auto Levels Dept')
        self.assertTrue(
            DepartmentLevel.objects.filter(department=new_dept, level=level).exists(),
        )


# ---------------------------------------------------------------------------
# DepartmentDetailView
# ---------------------------------------------------------------------------
class DepartmentDetailViewTests(DepartmentViewsTestBase):

    def test_detail_get(self):
        url = reverse('admin_department_detail', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['department'], self.dept)
        self.assertIn('subject_groups', resp.context)

    def test_detail_with_classes_and_levels(self):
        level = Level.objects.create(
            level_number=2, display_name='Year 2', subject=self.subject,
        )
        DepartmentLevel.objects.create(department=self.dept, level=level, order=2)
        cls = ClassRoom.objects.create(
            name='Class B', school=self.school, department=self.dept,
        )
        cls.levels.add(level)
        url = reverse('admin_department_detail', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('classes_by_level', resp.context)

    def test_detail_with_ungrouped_classes(self):
        """Classes with no levels should appear under 'No Level'."""
        ClassRoom.objects.create(
            name='Ungrouped', school=self.school, department=self.dept,
        )
        url = reverse('admin_department_detail', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertIn('No Level', resp.context['classes_by_level'])

    def test_detail_orphan_levels(self):
        """Levels with no matching department subject should be orphaned."""
        other_subj = Subject.objects.create(name='History', slug='history')
        level = Level.objects.create(
            level_number=3, display_name='Year 3', subject=other_subj,
        )
        DepartmentLevel.objects.create(department=self.dept, level=level, order=3)
        url = reverse('admin_department_detail', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertTrue(len(resp.context['orphan_levels']) > 0)


# ---------------------------------------------------------------------------
# DepartmentEditView
# ---------------------------------------------------------------------------
class DepartmentEditViewTests(DepartmentViewsTestBase):

    def test_edit_get(self):
        url = reverse('admin_department_edit', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['editing'])
        self.assertEqual(resp.context['form_data']['name'], 'Mathematics')

    def test_edit_post_update_name(self):
        url = reverse('admin_department_edit', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'name': 'Maths Dept',
            'description': 'Updated desc',
            'subjects': [str(self.subject.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertEqual(self.dept.name, 'Maths Dept')
        self.assertEqual(self.dept.description, 'Updated desc')

    def test_edit_post_empty_name_error(self):
        url = reverse('admin_department_edit', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'name': '', 'description': ''})
        self.assertEqual(resp.status_code, 200)  # re-renders form
        self.assertTrue(resp.context['editing'])

    def test_edit_post_add_new_subject(self):
        url = reverse('admin_department_edit', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'name': 'Mathematics',
            'description': '',
            'subjects': [str(self.subject.id), 'new'],
            'new_subject_name': 'Algebra',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(name='Algebra', school=self.school).exists())

    def test_edit_post_remove_subject(self):
        """Unselecting a subject should remove the DepartmentSubject link."""
        new_subj = Subject.objects.create(name='English', slug='english')
        DepartmentSubject.objects.create(department=self.dept, subject=new_subj, order=1)
        url = reverse('admin_department_edit', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        # Only select original subject, removing new_subj
        resp = self.client.post(url, {
            'name': 'Mathematics',
            'description': '',
            'subjects': [str(self.subject.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            DepartmentSubject.objects.filter(department=self.dept, subject=new_subj).exists(),
        )

    def test_edit_slug_collision(self):
        """Renaming to a name that collides with another dept slug."""
        Department.objects.create(school=self.school, name='Physics', slug='physics')
        url = reverse('admin_department_edit', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'name': 'Physics',
            'description': '',
            'subjects': [str(self.subject.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        # Slug should be physics-1 since 'physics' is already taken
        self.assertIn('physics', self.dept.slug)


# ---------------------------------------------------------------------------
# DepartmentAssignHoDView
# ---------------------------------------------------------------------------
class DepartmentAssignHoDViewTests(DepartmentViewsTestBase):

    def setUp(self):
        super().setUp()
        self.teacher = CustomUser.objects.create_user(
            username='teacher1', password='password1!', email='wlhtestmails+t1@gmail.com',
            first_name='John', last_name='Smith',
        )
        UserRole.objects.create(user=self.teacher, role=_create_role(Role.TEACHER))
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=self.teacher)

    def test_assign_hod_get(self):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('school_teachers', resp.context)

    def test_assign_existing_teacher_as_hod(self):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'assign_existing',
            'teacher_id': self.teacher.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertEqual(self.dept.head, self.teacher)
        # Should also have HoD role
        self.assertTrue(
            UserRole.objects.filter(user=self.teacher, role__name=Role.HEAD_OF_DEPARTMENT).exists(),
        )
        # Should be a department teacher
        self.assertTrue(
            DepartmentTeacher.objects.filter(department=self.dept, teacher=self.teacher).exists(),
        )

    def test_assign_existing_no_teacher_id(self):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'action': 'assign_existing'})
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertIsNone(self.dept.head)

    def test_assign_existing_teacher_not_in_school(self):
        other_teacher = CustomUser.objects.create_user(
            username='outsider', password='password1!', email='wlhtestmails+out@gmail.com',
        )
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'assign_existing',
            'teacher_id': other_teacher.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertIsNone(self.dept.head)

    @patch('classroom.views_department.send_staff_welcome_email')
    def test_create_new_hod(self, mock_email):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'create_new',
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'wlhtestmails+jane@gmail.com',
            'password': 'securepass123',
            'username': 'janedoe',
        })
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        new_user = CustomUser.objects.get(username='janedoe')
        self.assertEqual(self.dept.head, new_user)
        self.assertTrue(mock_email.called)

    @patch('classroom.views_department.send_staff_welcome_email')
    def test_create_new_hod_auto_username(self, mock_email):
        """When no username is provided, one is auto-generated from email."""
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'create_new',
            'first_name': 'Auto',
            'last_name': 'User',
            'email': 'wlhtestmails+autouser@gmail.com',
            'password': 'securepass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(email='wlhtestmails+autouser@gmail.com').exists())

    def test_create_new_hod_validation_errors(self):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'create_new',
            'first_name': '',
            'last_name': '',
            'email': 'invalid',
            'password': 'short',
        })
        self.assertEqual(resp.status_code, 200)  # re-renders form
        self.assertIn('form_data', resp.context)

    def test_create_new_hod_duplicate_email(self):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'create_new',
            'first_name': 'Dup',
            'last_name': 'User',
            'email': 'wlhtestmails+t1@gmail.com',  # already used by self.teacher
            'password': 'securepass123',
        })
        self.assertEqual(resp.status_code, 200)

    def test_invalid_action(self):
        url = reverse('admin_department_assign_hod', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'action': 'bogus'})
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# DepartmentManageTeachersView
# ---------------------------------------------------------------------------
class DepartmentManageTeachersViewTests(DepartmentViewsTestBase):

    def setUp(self):
        super().setUp()
        self.t1 = CustomUser.objects.create_user(
            username='teach_a', password='password1!', email='wlhtestmails+ta@gmail.com',
        )
        self.t2 = CustomUser.objects.create_user(
            username='teach_b', password='password1!', email='wlhtestmails+tb@gmail.com',
        )
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=self.t1)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=self.t2)

    def test_manage_teachers_get(self):
        url = reverse('admin_department_teachers', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('assigned_ids', resp.context)

    def test_manage_teachers_add(self):
        url = reverse('admin_department_teachers', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'teacher_ids': [str(self.t1.id), str(self.t2.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(DepartmentTeacher.objects.filter(department=self.dept).count(), 2)

    def test_manage_teachers_remove(self):
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.t1)
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.t2)
        url = reverse('admin_department_teachers', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        # Only keep t1
        resp = self.client.post(url, {'teacher_ids': [str(self.t1.id)]})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            DepartmentTeacher.objects.filter(department=self.dept, teacher=self.t1).exists(),
        )
        self.assertFalse(
            DepartmentTeacher.objects.filter(department=self.dept, teacher=self.t2).exists(),
        )

    def test_manage_teachers_no_changes(self):
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.t1)
        url = reverse('admin_department_teachers', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'teacher_ids': [str(self.t1.id)]})
        self.assertEqual(resp.status_code, 302)

    def test_manage_teachers_head_not_removed(self):
        """The HoD should not be removed even if unchecked."""
        self.dept.head = self.t1
        self.dept.save()
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.t1)
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.t2)
        url = reverse('admin_department_teachers', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        # Submit with no teachers selected
        resp = self.client.post(url, {'teacher_ids': []})
        self.assertEqual(resp.status_code, 302)
        # HoD (t1) should still be there
        self.assertTrue(
            DepartmentTeacher.objects.filter(department=self.dept, teacher=self.t1).exists(),
        )

    def test_manage_teachers_invalid_ids(self):
        url = reverse('admin_department_teachers', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'teacher_ids': ['abc', 'xyz']})
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# DepartmentAssignClassesView
# ---------------------------------------------------------------------------
class DepartmentAssignClassesViewTests(DepartmentViewsTestBase):

    def setUp(self):
        super().setUp()
        self.cls1 = ClassRoom.objects.create(
            name='Class 1', school=self.school,
        )
        self.cls2 = ClassRoom.objects.create(
            name='Class 2', school=self.school,
        )

    def test_assign_classes_get(self):
        url = reverse('admin_department_assign_classes', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('all_classes', resp.context)

    def test_assign_classes_post(self):
        url = reverse('admin_department_assign_classes', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'class_ids': [str(self.cls1.id), str(self.cls2.id)],
        })
        self.assertEqual(resp.status_code, 302)
        self.cls1.refresh_from_db()
        self.cls2.refresh_from_db()
        self.assertEqual(self.cls1.department, self.dept)
        self.assertEqual(self.cls2.department, self.dept)

    def test_assign_classes_unassign(self):
        self.cls1.department = self.dept
        self.cls1.save()
        url = reverse('admin_department_assign_classes', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        # Submit with empty selection
        resp = self.client.post(url, {'class_ids': []})
        self.assertEqual(resp.status_code, 302)
        self.cls1.refresh_from_db()
        self.assertIsNone(self.cls1.department)

    def test_assign_classes_invalid_ids(self):
        url = reverse('admin_department_assign_classes', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'class_ids': ['bad']})
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# DepartmentManageLevelsView
# ---------------------------------------------------------------------------
class DepartmentManageLevelsViewTests(DepartmentViewsTestBase):

    def setUp(self):
        super().setUp()
        self.level = Level.objects.create(
            level_number=4, display_name='Year 4', subject=self.subject,
        )

    def test_manage_levels_get(self):
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('level_data', resp.context)

    def test_manage_levels_add(self):
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'level_ids': [str(self.level.id)],
            f'local_name_{self.level.id}': 'Custom Year 4',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            DepartmentLevel.objects.filter(department=self.dept, level=self.level).exists(),
        )

    def test_manage_levels_remove(self):
        DepartmentLevel.objects.create(
            department=self.dept, level=self.level, order=4,
        )
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        # Post with no levels selected
        resp = self.client.post(url, {'level_ids': []})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            DepartmentLevel.objects.filter(department=self.dept, level=self.level).exists(),
        )

    def test_manage_levels_update_local_name(self):
        DepartmentLevel.objects.create(
            department=self.dept, level=self.level, order=4,
            local_display_name='Old Name',
        )
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'level_ids': [str(self.level.id)],
            f'local_name_{self.level.id}': 'New Name',
        })
        self.assertEqual(resp.status_code, 302)
        dl = DepartmentLevel.objects.get(department=self.dept, level=self.level)
        self.assertEqual(dl.local_display_name, 'New Name')

    def test_manage_levels_no_changes(self):
        DepartmentLevel.objects.create(
            department=self.dept, level=self.level, order=4,
            local_display_name='Same',
        )
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'level_ids': [str(self.level.id)],
            f'local_name_{self.level.id}': 'Same',
        })
        self.assertEqual(resp.status_code, 302)

    def test_manage_levels_no_subjects_uses_custom(self):
        """Department with no subjects shows custom levels (200+)."""
        no_subj_dept = Department.objects.create(
            school=self.school, name='Custom Dept', slug='custom-dept',
        )
        custom_level = Level.objects.create(
            level_number=200, display_name='Custom L1', school=self.school,
        )
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': no_subj_dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_manage_levels_invalid_ids(self):
        url = reverse('admin_department_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'level_ids': ['bad']})
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# DepartmentUpdateFeeView
# ---------------------------------------------------------------------------
class DepartmentUpdateFeeViewTests(DepartmentViewsTestBase):

    def test_update_fee(self):
        url = reverse('admin_department_update_fee', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'default_fee': '49.99'})
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertEqual(self.dept.default_fee, Decimal('49.99'))

    def test_update_fee_clear(self):
        self.dept.default_fee = Decimal('10.00')
        self.dept.save()
        url = reverse('admin_department_update_fee', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'default_fee': ''})
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertIsNone(self.dept.default_fee)

    def test_update_fee_invalid(self):
        url = reverse('admin_department_update_fee', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'default_fee': 'abc'})
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertIsNone(self.dept.default_fee)


# ---------------------------------------------------------------------------
# DepartmentToggleActiveView
# ---------------------------------------------------------------------------
class DepartmentToggleActiveViewTests(DepartmentViewsTestBase):

    def test_toggle_deactivate(self):
        url = reverse('admin_department_toggle_active', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertFalse(self.dept.is_active)

    def test_toggle_activate(self):
        self.dept.is_active = False
        self.dept.save()
        url = reverse('admin_department_toggle_active', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertTrue(self.dept.is_active)


# ---------------------------------------------------------------------------
# DepartmentDeleteView
# ---------------------------------------------------------------------------
class DepartmentDeleteViewTests(DepartmentViewsTestBase):

    def test_delete_empty_department(self):
        url = reverse('admin_department_delete', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertFalse(self.dept.is_active)

    def test_delete_blocked_by_classes(self):
        ClassRoom.objects.create(
            name='Blocking Class', school=self.school, department=self.dept,
        )
        url = reverse('admin_department_delete', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertTrue(self.dept.is_active)  # not deactivated

    def test_delete_blocked_by_teachers(self):
        teacher = CustomUser.objects.create_user(
            username='blocker', password='password1!', email='wlhtestmails+blocker@gmail.com',
        )
        DepartmentTeacher.objects.create(department=self.dept, teacher=teacher)
        url = reverse('admin_department_delete', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertTrue(self.dept.is_active)

    def test_delete_blocked_by_both(self):
        teacher = CustomUser.objects.create_user(
            username='blocker2', password='password1!', email='wlhtestmails+blocker2@gmail.com',
        )
        DepartmentTeacher.objects.create(department=self.dept, teacher=teacher)
        ClassRoom.objects.create(
            name='Class X', school=self.school, department=self.dept,
        )
        url = reverse('admin_department_delete', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.dept.refresh_from_db()
        self.assertTrue(self.dept.is_active)


# ---------------------------------------------------------------------------
# DepartmentSubjectLevelRemoveView
# ---------------------------------------------------------------------------
class DepartmentSubjectLevelRemoveViewTests(DepartmentViewsTestBase):

    def test_remove_level_mapping(self):
        level = Level.objects.create(
            level_number=5, display_name='Year 5', subject=self.subject,
        )
        DepartmentLevel.objects.create(department=self.dept, level=level, order=5)
        url = reverse('admin_department_subject_level_remove', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
            'level_id': level.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            DepartmentLevel.objects.filter(department=self.dept, level=level).exists(),
        )

    def test_remove_unmapped_level(self):
        level = Level.objects.create(
            level_number=6, display_name='Year 6', subject=self.subject,
        )
        url = reverse('admin_department_subject_level_remove', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
            'level_id': level.id,
        })
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# DepartmentSubjectLevelsView
# ---------------------------------------------------------------------------
class DepartmentSubjectLevelsViewTests(DepartmentViewsTestBase):

    def test_subject_levels_get(self):
        level = Level.objects.create(
            level_number=7, display_name='Year 7', subject=self.subject,
        )
        DepartmentLevel.objects.create(department=self.dept, level=level, order=7)
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('subject_groups', resp.context)

    def test_add_existing_subject(self):
        new_subj = Subject.objects.create(name='Science', slug='science')
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'add_subject',
            'add_subject_id': str(new_subj.id),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            DepartmentSubject.objects.filter(department=self.dept, subject=new_subj).exists(),
        )

    def test_add_subject_already_assigned(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'add_subject',
            'add_subject_id': str(self.subject.id),
        })
        self.assertEqual(resp.status_code, 302)
        # Should still have exactly one link
        self.assertEqual(
            DepartmentSubject.objects.filter(department=self.dept, subject=self.subject).count(), 1,
        )

    def test_add_new_subject_by_name(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'add_subject',
            'new_subject_name': 'Drama',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(name='Drama', school=self.school).exists())

    def test_add_subject_no_selection_or_name(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'action': 'add_subject'})
        self.assertEqual(resp.status_code, 302)

    def test_edit_subject_fee(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject_fee',
            'subject_id': str(self.subject.id),
            'fee_override': '25.00',
        })
        self.assertEqual(resp.status_code, 302)
        ds = DepartmentSubject.objects.get(department=self.dept, subject=self.subject)
        self.assertEqual(ds.fee_override, Decimal('25.00'))

    def test_edit_subject_fee_clear(self):
        ds = DepartmentSubject.objects.get(department=self.dept, subject=self.subject)
        ds.fee_override = Decimal('10.00')
        ds.save()
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject_fee',
            'subject_id': str(self.subject.id),
            'fee_override': '',
        })
        self.assertEqual(resp.status_code, 302)
        ds.refresh_from_db()
        self.assertIsNone(ds.fee_override)

    def test_edit_subject_fee_invalid(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject_fee',
            'subject_id': str(self.subject.id),
            'fee_override': 'not-a-number',
        })
        self.assertEqual(resp.status_code, 302)

    def test_edit_subject_rename(self):
        school_subj = Subject.objects.create(
            name='Old Name', slug='old-name', school=self.school,
        )
        DepartmentSubject.objects.create(department=self.dept, subject=school_subj, order=1)
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject',
            'subject_id': str(school_subj.id),
            'subject_name': 'New Name',
        })
        self.assertEqual(resp.status_code, 302)
        school_subj.refresh_from_db()
        self.assertEqual(school_subj.name, 'New Name')

    def test_edit_subject_not_found(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject',
            'subject_id': '99999',
            'subject_name': 'Anything',
        })
        self.assertEqual(resp.status_code, 302)

    def test_edit_subject_move_to_other_department(self):
        other_dept = Department.objects.create(
            school=self.school, name='English', slug='english',
        )
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject',
            'subject_id': str(self.subject.id),
            'subject_name': self.subject.name,
            'new_department_id': str(other_dept.id),
        })
        self.assertEqual(resp.status_code, 302)
        # Subject should now be in other_dept
        self.assertTrue(
            DepartmentSubject.objects.filter(department=other_dept, subject=self.subject).exists(),
        )
        self.assertFalse(
            DepartmentSubject.objects.filter(department=self.dept, subject=self.subject).exists(),
        )

    def test_edit_subject_move_already_exists_in_target(self):
        other_dept = Department.objects.create(
            school=self.school, name='English', slug='english-2',
        )
        DepartmentSubject.objects.create(department=other_dept, subject=self.subject, order=0)
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_subject',
            'subject_id': str(self.subject.id),
            'subject_name': self.subject.name,
            'new_department_id': str(other_dept.id),
        })
        self.assertEqual(resp.status_code, 302)
        # Should still be in original dept since target already has it
        self.assertTrue(
            DepartmentSubject.objects.filter(department=self.dept, subject=self.subject).exists(),
        )

    def test_edit_level(self):
        level = Level.objects.create(
            level_number=8, display_name='Year 8', subject=self.subject,
        )
        DepartmentLevel.objects.create(department=self.dept, level=level, order=8)
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_level',
            'level_id': str(level.id),
            'display_name': 'Year Eight',
            'description': 'Updated',
            'fee_override': '30.00',
        })
        self.assertEqual(resp.status_code, 302)
        level.refresh_from_db()
        self.assertEqual(level.display_name, 'Year Eight')
        dl = DepartmentLevel.objects.get(department=self.dept, level=level)
        self.assertEqual(dl.fee_override, Decimal('30.00'))

    def test_edit_level_not_found(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_level',
            'level_id': '99999',
            'display_name': 'Nope',
        })
        self.assertEqual(resp.status_code, 302)

    def test_edit_level_no_name(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'action': 'edit_level',
            'level_id': '1',
            'display_name': '',
        })
        self.assertEqual(resp.status_code, 302)

    def test_add_level_default_action(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'level_name': 'Custom Level',
            'level_description': 'A custom level',
            'subject_id': str(self.subject.id),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Level.objects.filter(display_name='Custom Level').exists())

    def test_add_level_no_name(self):
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {'level_name': ''})
        self.assertEqual(resp.status_code, 302)

    def test_add_level_no_subject_uses_first(self):
        """When no subject_id is given, uses the first department subject."""
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.post(url, {
            'level_name': 'Auto Subject Level',
        })
        self.assertEqual(resp.status_code, 302)
        new_level = Level.objects.get(display_name='Auto Subject Level')
        self.assertEqual(new_level.subject, self.subject)

    def test_add_level_no_subject_auto_creates(self):
        """Department with no subjects auto-creates one from dept name."""
        empty_dept = Department.objects.create(
            school=self.school, name='Music', slug='music',
        )
        url = reverse('admin_department_subject_levels', kwargs={
            'school_id': self.school.id, 'dept_id': empty_dept.id,
        })
        resp = self.client.post(url, {
            'level_name': 'Grade 1 Music',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(name='Music', school=self.school).exists())


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------
class DepartmentAuthorizationTests(DepartmentViewsTestBase):

    def test_non_admin_cannot_access_list(self):
        student = CustomUser.objects.create_user(
            username='student1', password='password1!', email='wlhtestmails+s1@gmail.com',
        )
        UserRole.objects.create(user=student, role=_create_role(Role.STUDENT))
        self.client.login(username='student1', password='password1!')
        url = reverse('admin_school_departments', kwargs={'school_id': self.school.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)  # Redirects to public_home

    def test_wrong_school_admin_gets_404(self):
        other_user = CustomUser.objects.create_user(
            username='other_admin', password='password1!', email='wlhtestmails+other@gmail.com',
        )
        UserRole.objects.create(user=other_user, role=_create_role(Role.HEAD_OF_INSTITUTE))
        other_school = School.objects.create(
            name='Other School', slug='other-school', admin=other_user,
        )
        self.client.login(username='other_admin', password='password1!')
        url = reverse('admin_department_detail', kwargs={
            'school_id': self.school.id, 'dept_id': self.dept.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
