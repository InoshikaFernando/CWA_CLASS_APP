"""
Tests to verify that sidebar templates contain the correct navigation links.

Each role-specific sidebar is tested by hitting the main dashboard view for
that role and asserting that key URL paths/names appear in the response HTML.
This prevents regressions like a missing Billing link going undetected.
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, SchoolTeacher, DepartmentTeacher, DepartmentSubject,
    Subject,
)


# ---------------------------------------------------------------------------
# Helpers (same patterns used in test_views_coverage.py)
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


def _setup_school(admin_user, slug='test-school'):
    """Create a school with an active subscription. Returns (school, subscription)."""
    school = School.objects.create(name='Test School', slug=slug, admin=admin_user)
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{slug}', price=Decimal('89.00'),
        stripe_price_id='price_test', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return school, sub


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
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=head,
            defaults={'role': 'head_of_department'},
        )
    return dept


# ===========================================================================
# sidebar_admin.html — Admin / Institute Owner sidebar
# ===========================================================================

class SidebarAdminNavigationTests(TestCase):
    """Verify the admin sidebar (sidebar_admin.html) contains all expected links."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username='sidebar_admin', password='pass12345', email='sb_admin@test.com',
        )
        _assign_role(cls.user, Role.ADMIN)
        cls.school, cls.sub = _setup_school(cls.user, slug='sb-admin-school')

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_admin', password='pass12345')

    def test_admin_sidebar_contains_dashboard_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/admin-dashboard/')

    def test_admin_sidebar_contains_schools_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/schools/')

    def test_admin_sidebar_contains_teachers_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/teachers/')

    def test_admin_sidebar_contains_students_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/students/')

    def test_admin_sidebar_contains_academic_years_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/academic-years/')

    def test_admin_sidebar_contains_school_hierarchy_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, reverse('school_hierarchy_auto'))

    def test_admin_sidebar_contains_enrollment_requests_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, reverse('enrollment_requests'))

    def test_admin_sidebar_contains_email_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, reverse('email_dashboard'))

    def test_admin_sidebar_contains_billing_link(self):
        """Regression test: billing link was missing from sidebar_admin.html."""
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, reverse('institute_subscription_dashboard'))

    def test_admin_sidebar_contains_billing_label(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '>Billing</span>')

    def test_admin_sidebar_contains_profile_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, reverse('profile'))


# ===========================================================================
# sidebar_hod.html — HoI / Institute Owner sidebar
# ===========================================================================

class SidebarHodNavigationTests(TestCase):
    """Verify the HoD/HoI sidebar (sidebar_hod.html) contains all expected links.

    sidebar_hod.html is used for both institute_owner and head_of_institute roles.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username='sidebar_hoi', password='pass12345', email='sb_hoi@test.com',
        )
        _assign_role(cls.user, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.user, slug='sb-hoi-school')
        cls.dept = _setup_department(cls.school, head=cls.user)

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_hoi', password='pass12345')

    def _get_dashboard(self):
        return self.client.get(reverse('hod_overview'))

    def test_hod_sidebar_contains_dashboard_link(self):
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('hod_overview'))

    def test_hod_sidebar_contains_school_hierarchy_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('school_hierarchy_auto'))

    def test_hod_sidebar_contains_schools_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('admin_dashboard'))

    def test_hod_sidebar_contains_departments_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('admin_manage_departments'))

    def test_hod_sidebar_contains_subjects_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('admin_manage_subjects'))

    def test_hod_sidebar_contains_teachers_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('admin_manage_teachers'))

    def test_hod_sidebar_contains_students_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('admin_manage_students'))

    def test_hod_sidebar_contains_enrollment_requests_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('enrollment_requests'))

    def test_hod_sidebar_contains_billing_link(self):
        """Regression test: billing link must be present in sidebar_hod.html."""
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('institute_subscription_dashboard'))

    def test_hod_sidebar_contains_billing_label(self):
        resp = self._get_dashboard()
        self.assertContains(resp, '>Billing</span>')

    def test_hod_sidebar_contains_profile_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('profile'))

    def test_hod_sidebar_contains_workload_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_workload'))

    def test_hod_sidebar_contains_classes_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_manage_classes'))

    def test_hod_sidebar_contains_reports_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_reports'))


# ===========================================================================
# sidebar_hod_department.html — HoD-only (department-scoped) sidebar
# ===========================================================================

class SidebarHodDepartmentNavigationTests(TestCase):
    """Verify the HoD-only sidebar (sidebar_hod_department.html) contains expected links.

    This sidebar is shown when the user is a head_of_department but NOT
    head_of_institute or institute_owner.
    """

    @classmethod
    def setUpTestData(cls):
        # Create an HoI to own the school
        cls.hoi = CustomUser.objects.create_user(
            username='sb_dept_hoi', password='pass12345', email='sb_dept_hoi@test.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-dept-school')

        # Create the HoD user (only HoD role, not HoI/Owner)
        cls.hod = CustomUser.objects.create_user(
            username='sidebar_hod_dept', password='pass12345', email='sb_hod_dept@test.com',
        )
        _assign_role(cls.hod, Role.HEAD_OF_DEPARTMENT)
        cls.dept = _setup_department(cls.school, head=cls.hod)

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_hod_dept', password='pass12345')

    def _get_dashboard(self):
        return self.client.get(reverse('hod_overview'))

    def test_hod_dept_sidebar_contains_dashboard_link(self):
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('hod_overview'))

    def test_hod_dept_sidebar_contains_school_hierarchy_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('school_hierarchy_auto'))

    def test_hod_dept_sidebar_contains_classes_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_manage_classes'))

    def test_hod_dept_sidebar_contains_academic_levels_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_subject_levels'))

    def test_hod_dept_sidebar_contains_workload_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_workload'))

    def test_hod_dept_sidebar_contains_reports_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('hod_reports'))

    def test_hod_dept_sidebar_contains_profile_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('profile'))


# ===========================================================================
# sidebar_teacher.html — Teacher sidebar
# ===========================================================================

class SidebarTeacherNavigationTests(TestCase):
    """Verify the teacher sidebar (sidebar_teacher.html) contains expected links."""

    @classmethod
    def setUpTestData(cls):
        # Create HoI + school
        cls.hoi = CustomUser.objects.create_user(
            username='sb_teach_hoi', password='pass12345', email='sb_teach_hoi@test.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-teacher-school')

        # Create teacher
        cls.teacher = CustomUser.objects.create_user(
            username='sidebar_teacher', password='pass12345', email='sb_teacher@test.com',
        )
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_teacher', password='pass12345')

    def _get_dashboard(self):
        return self.client.get(reverse('teacher_dashboard'))

    def test_teacher_sidebar_contains_dashboard_link(self):
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('teacher_dashboard'))

    def test_teacher_sidebar_contains_my_classes_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, '/hub/')

    def test_teacher_sidebar_contains_enrollment_requests_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('enrollment_requests'))

    def test_teacher_sidebar_contains_school_hierarchy_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('school_hierarchy_auto'))

    def test_teacher_sidebar_contains_topics_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('topics'))

    def test_teacher_sidebar_contains_upload_questions_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('upload_questions'))

    def test_teacher_sidebar_contains_profile_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('profile'))


# ===========================================================================
# sidebar_senior_teacher.html — Senior Teacher sidebar
# ===========================================================================

class SidebarSeniorTeacherNavigationTests(TestCase):
    """Verify the senior teacher sidebar (sidebar_senior_teacher.html) contains expected links."""

    @classmethod
    def setUpTestData(cls):
        # Create HoI + school
        cls.hoi = CustomUser.objects.create_user(
            username='sb_sr_hoi', password='pass12345', email='sb_sr_hoi@test.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-sr-teacher-school')

        # Create senior teacher
        cls.teacher = CustomUser.objects.create_user(
            username='sidebar_sr_teacher', password='pass12345', email='sb_sr_teacher@test.com',
        )
        _assign_role(cls.teacher, Role.SENIOR_TEACHER)
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.teacher, role='senior_teacher',
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_sr_teacher', password='pass12345')

    def _get_dashboard(self):
        return self.client.get(reverse('teacher_dashboard'))

    def test_senior_teacher_sidebar_contains_dashboard_link(self):
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('teacher_dashboard'))

    def test_senior_teacher_sidebar_contains_my_classes_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, '/hub/')

    def test_senior_teacher_sidebar_contains_enrollment_requests_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('enrollment_requests'))

    def test_senior_teacher_sidebar_contains_school_hierarchy_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('school_hierarchy_auto'))

    def test_senior_teacher_sidebar_contains_topics_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('topics'))

    def test_senior_teacher_sidebar_contains_upload_questions_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('upload_questions'))

    def test_senior_teacher_sidebar_contains_profile_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('profile'))

    def test_senior_teacher_sidebar_contains_dashboard_label(self):
        resp = self._get_dashboard()
        self.assertContains(resp, '>Dashboard</span>')
