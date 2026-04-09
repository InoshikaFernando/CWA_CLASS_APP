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
    Subject, ParentStudent, SchoolStudent,
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
        SchoolTeacher.objects.update_or_create(
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
            username='sidebar_admin', password='password1!', email='wlhtestmails+sb_admin@gmail.com',
        )
        _assign_role(cls.user, Role.ADMIN)
        cls.school, cls.sub = _setup_school(cls.user, slug='sb-admin-school')

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_admin', password='password1!')

    def test_admin_sidebar_contains_dashboard_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/admin-dashboard/')

    def test_admin_sidebar_contains_schools_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/schools/')

    def test_admin_sidebar_contains_teachers_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/manage-teachers/')

    def test_admin_sidebar_contains_students_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/manage-students/')

    def test_admin_sidebar_contains_academic_years_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '/admin-dashboard/manage-terms/')

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

    def test_admin_sidebar_contains_settings_link(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, reverse('admin_manage_settings'))

    def test_admin_sidebar_contains_settings_label(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, '>Settings</span>')


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
            username='sidebar_hoi', password='password1!', email='wlhtestmails+sb_hoi@gmail.com',
        )
        _assign_role(cls.user, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.user, slug='sb-hoi-school')
        cls.dept = _setup_department(cls.school, head=cls.user)

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_hoi', password='password1!')

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

    def test_hod_sidebar_contains_settings_link(self):
        resp = self._get_dashboard()
        self.assertContains(resp, reverse('admin_manage_settings'))

    def test_hod_sidebar_contains_settings_label(self):
        resp = self._get_dashboard()
        self.assertContains(resp, '>Settings</span>')


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
            username='sb_dept_hoi', password='password1!', email='wlhtestmails+sb_dept_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-dept-school')

        # Create the HoD user (only HoD role, not HoI/Owner)
        cls.hod = CustomUser.objects.create_user(
            username='sidebar_hod_dept', password='password1!', email='wlhtestmails+sb_hod_dept@gmail.com',
        )
        _assign_role(cls.hod, Role.HEAD_OF_DEPARTMENT)
        cls.dept = _setup_department(cls.school, head=cls.hod)

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_hod_dept', password='password1!')

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
            username='sb_teach_hoi', password='password1!', email='wlhtestmails+sb_teach_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-teacher-school')

        # Create teacher
        cls.teacher = CustomUser.objects.create_user(
            username='sidebar_teacher', password='password1!', email='wlhtestmails+sb_teacher@gmail.com',
        )
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(school=cls.school, teacher=cls.teacher, defaults={'role': 'teacher'})

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_teacher', password='password1!')

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
            username='sb_sr_hoi', password='password1!', email='wlhtestmails+sb_sr_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-sr-teacher-school')

        # Create senior teacher
        cls.teacher = CustomUser.objects.create_user(
            username='sidebar_sr_teacher', password='password1!', email='wlhtestmails+sb_sr_teacher@gmail.com',
        )
        _assign_role(cls.teacher, Role.SENIOR_TEACHER)
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.teacher, defaults={'role': 'senior_teacher'})

    def setUp(self):
        self.client = Client()
        self.client.login(username='sidebar_sr_teacher', password='password1!')

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


# ===========================================================================
# sidebar_parent.html — Parent sidebar scenarios
# ===========================================================================

def _create_parent(username, email):
    user = CustomUser.objects.create_user(username=username, password='password1!', email=email)
    _assign_role(user, Role.PARENT)
    return user


def _create_student(username, email):
    user = CustomUser.objects.create_user(username=username, password='password1!', email=email)
    _assign_role(user, Role.STUDENT)
    return user


def _create_individual_student(username, email):
    user = CustomUser.objects.create_user(username=username, password='password1!', email=email)
    _assign_role(user, Role.INDIVIDUAL_STUDENT)
    return user


class SidebarParentWithSchoolStudentTests(TestCase):
    """Parent linked to a school student — Academics section must be visible."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sb_par_hoi', password='password1!', email='wlhtestmails+sb_par_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-par-school')

        cls.student = _create_student('sb_par_student', 'wlhtestmails+sb_par_stu@gmail.com')
        SchoolStudent.objects.create(
            student=cls.student, school=cls.school, student_id_code='STU-001-0001',
        )

        cls.parent = _create_parent('sb_par_school_parent', 'wlhtestmails+sb_par_school@gmail.com')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school,
            relationship='guardian', is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='sb_par_school_parent', password='password1!')

    def test_academics_section_visible_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Academics')

    def test_homework_link_visible_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_homework'))

    def test_classes_link_visible_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_classes'))

    def test_attendance_link_visible_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_attendance'))

    def test_progress_link_visible_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_progress'))

    def test_academics_section_visible_on_invoices_page(self):
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Academics')

    def test_academics_section_visible_on_payments_page(self):
        resp = self.client.get(reverse('parent_payment_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Academics')

    def test_academics_section_visible_on_billing_page(self):
        resp = self.client.get(reverse('parent_billing'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Academics')

    def test_billing_links_always_visible(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_invoices'))
        self.assertContains(resp, reverse('parent_payment_history'))

    def test_school_name_shown_in_child_switcher(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, self.school.name)


class SidebarParentWithIndividualStudentOnlyTests(TestCase):
    """Parent linked only to an individual student — Academics section must be hidden."""

    @classmethod
    def setUpTestData(cls):
        cls.individual = _create_individual_student(
            'sb_par_ind_stu', 'wlhtestmails+sb_par_ind_stu@gmail.com',
        )
        cls.parent = _create_parent('sb_par_ind_parent', 'wlhtestmails+sb_par_ind@gmail.com')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.individual, school=None,
            relationship='guardian', is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='sb_par_ind_parent', password='password1!')

    def test_academics_section_hidden_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '>Academics<')

    def test_homework_link_hidden_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotContains(resp, reverse('parent_homework'))

    def test_classes_link_hidden_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotContains(resp, reverse('parent_classes'))

    def test_attendance_link_hidden_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotContains(resp, reverse('parent_attendance'))

    def test_progress_link_hidden_on_dashboard(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotContains(resp, reverse('parent_progress'))

    def test_academics_section_hidden_on_invoices_page(self):
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '>Academics<')

    def test_academics_section_hidden_on_payments_page(self):
        resp = self.client.get(reverse('parent_payment_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '>Academics<')

    def test_billing_links_always_visible(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_invoices'))
        self.assertContains(resp, reverse('parent_payment_history'))

    def test_individual_label_shown_in_child_switcher(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, 'Individual')


class SidebarParentWithMixedStudentsTests(TestCase):
    """Parent linked to both a school student and an individual student.

    Academics are shown/hidden depending on which child is active.
    """

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sb_par_mix_hoi', password='password1!', email='wlhtestmails+sb_par_mix_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-par-mix-school')

        cls.school_student = _create_student('sb_par_mix_stu', 'wlhtestmails+sb_par_mix_stu@gmail.com')
        SchoolStudent.objects.create(
            student=cls.school_student, school=cls.school, student_id_code='STU-002-0001',
        )

        cls.individual = _create_individual_student(
            'sb_par_mix_ind', 'wlhtestmails+sb_par_mix_ind@gmail.com',
        )

        cls.parent = _create_parent('sb_par_mix_parent', 'wlhtestmails+sb_par_mix@gmail.com')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.school_student, school=cls.school,
            relationship='guardian', is_active=True,
        )
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.individual, school=None,
            relationship='guardian', is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='sb_par_mix_parent', password='password1!')

    def test_academics_visible_when_school_student_active(self):
        self.client.post(reverse('parent_switch_child', args=[self.school_student.pk]))
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, 'Academics')

    def test_academics_hidden_when_individual_student_active(self):
        self.client.post(reverse('parent_switch_child', args=[self.individual.pk]))
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotContains(resp, '>Academics<')

    def test_homework_visible_when_school_student_active(self):
        self.client.post(reverse('parent_switch_child', args=[self.school_student.pk]))
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, reverse('parent_homework'))

    def test_homework_hidden_when_individual_student_active(self):
        self.client.post(reverse('parent_switch_child', args=[self.individual.pk]))
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertNotContains(resp, reverse('parent_homework'))

    def test_both_children_appear_in_switcher(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, self.school_student.first_name)
        self.assertContains(resp, self.individual.first_name)

    def test_individual_label_shown_for_individual_in_switcher(self):
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertContains(resp, 'Individual')


# ===========================================================================
# sidebar_accountant.html — Accountant sidebar
# ===========================================================================

class SidebarAccountantNavigationTests(TestCase):
    """Verify the accountant sidebar contains all expected links."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sb_acc_hoi', password='password1!', email='wlhtestmails+sb_acc_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-acc-school')

        cls.accountant = CustomUser.objects.create_user(
            username='sb_accountant', password='password1!', email='wlhtestmails+sb_accountant@gmail.com',
        )
        _assign_role(cls.accountant, Role.ACCOUNTANT)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.accountant, role='accountant')

    def setUp(self):
        self.client = Client()
        self.client.login(username='sb_accountant', password='password1!')

    def test_accountant_sidebar_contains_dashboard_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('accounting_dashboard'))

    def test_accountant_sidebar_contains_packages_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertContains(resp, reverse('accounting_packages'))

    def test_accountant_sidebar_contains_user_stats_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertContains(resp, reverse('accounting_users'))

    def test_accountant_sidebar_contains_export_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertContains(resp, reverse('accounting_export'))

    def test_accountant_sidebar_contains_invoices_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertContains(resp, reverse('invoice_list'))

    def test_accountant_sidebar_contains_generate_invoices_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertContains(resp, reverse('generate_invoices'))

    def test_accountant_sidebar_contains_profile_link(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertContains(resp, reverse('profile'))


# ===========================================================================
# sidebar_student.html — School Student sidebar
# ===========================================================================

class SidebarSchoolStudentNavigationTests(TestCase):
    """Verify the school student sidebar contains all expected links."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sb_stu_hoi', password='password1!', email='wlhtestmails+sb_stu_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='sb-stu-school')

        cls.student = CustomUser.objects.create_user(
            username='sb_school_student', password='password1!', email='wlhtestmails+sb_stu@gmail.com',
        )
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(
            student=cls.student, school=cls.school, student_id_code='STU-003-0001',
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='sb_school_student', password='password1!')

    def test_student_sidebar_contains_progress_link(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('student_dashboard'))

    def test_student_sidebar_contains_homework_link(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertContains(resp, reverse('homework:student_list'))

    def test_student_sidebar_contains_attendance_link(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertContains(resp, reverse('student_attendance_history'))

    def test_student_sidebar_contains_help_link(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertContains(resp, reverse('help:help_centre'))

    def test_student_sidebar_contains_profile_link(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertContains(resp, reverse('profile'))


# ===========================================================================
# sidebar_student.html — Individual Student sidebar
# ===========================================================================

class SidebarIndividualStudentNavigationTests(TestCase):
    """Verify the individual student sidebar contains all expected links."""

    @classmethod
    def setUpTestData(cls):
        from billing.models import Package, Subscription
        cls.student = CustomUser.objects.create_user(
            username='sb_ind_student', password='password1!', email='wlhtestmails+sb_ind_stu@gmail.com',
        )
        _assign_role(cls.student, Role.INDIVIDUAL_STUDENT)
        pkg, _ = Package.objects.get_or_create(
            name='Test', defaults={'price': 0, 'stripe_price_id': 'price_test', 'is_active': True},
        )
        Subscription.objects.create(
            user=cls.student, package=pkg,
            status=Subscription.STATUS_ACTIVE,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='sb_ind_student', password='password1!')

    def test_individual_student_sidebar_contains_home_link(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/hub/')

    def test_individual_student_sidebar_contains_progress_link(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertContains(resp, reverse('student_dashboard'))

    def test_individual_student_sidebar_contains_attendance_link(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertContains(resp, reverse('student_attendance_history'))

    def test_individual_student_sidebar_contains_billing_link(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertContains(resp, reverse('change_package'))

    def test_individual_student_sidebar_contains_help_link(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertContains(resp, reverse('help:help_centre'))

    def test_individual_student_sidebar_contains_profile_link(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertContains(resp, reverse('profile'))
