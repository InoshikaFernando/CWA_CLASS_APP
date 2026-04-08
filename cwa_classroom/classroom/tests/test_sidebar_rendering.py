"""
Tests to verify that the correct sidebar is rendered in the HTML response for each
user role, and that role-specific links are present or absent as expected.

The sidebar is selected server-side in base.html based on the `active_role` context
variable (set by the `user_role` context processor from the session or primary role).
No Selenium is needed — checking the response HTML is sufficient.

Run with:
    python manage.py test classroom.tests.test_sidebar_rendering
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, Package, SchoolSubscription, Subscription
from classroom.models import (
    School,
    SchoolTeacher,
    SchoolStudent,
    ClassRoom,
    ClassStudent,
    Department,
    Subject,
    DepartmentSubject,
    DepartmentTeacher,
)


# ---------------------------------------------------------------------------
# Shared helpers (mirroring test_sidebar_navigation.py conventions)
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


def _setup_school(admin_user, slug):
    """Create a school with an active subscription. Returns (school, subscription)."""
    school = School.objects.create(name='Test School', slug=slug, admin=admin_user)
    plan = InstitutePlan.objects.create(
        name='Basic',
        slug=f'basic-{slug}',
        price=Decimal('89.00'),
        stripe_price_id='price_test',
        class_limit=50,
        student_limit=500,
        invoice_limit_yearly=500,
        extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return school, sub


def _setup_department(school, head=None):
    dept = Department.objects.create(
        school=school, name='Mathematics', slug='maths-dept', head=head,
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


# ---------------------------------------------------------------------------
# 1 & 2 & 3: Student sidebar tests
# ---------------------------------------------------------------------------

class StudentSidebarTests(TestCase):
    """Tests for the student sidebar (sidebar_student.html)."""

    @classmethod
    def setUpTestData(cls):
        # HoI to own the school
        cls.hoi = CustomUser.objects.create_user(
            username='srtest_hoi',
            password='password1!',
            email='wlhtestmails+srtest_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='srtest-student-school')

        # Plain student — no class enrolment
        cls.student_no_class = CustomUser.objects.create_user(
            username='srtest_student_noclass',
            password='password1!',
            email='wlhtestmails+srtest_student_noclass@gmail.com',
        )
        _assign_role(cls.student_no_class, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student_no_class)

        # Student WITH a class enrolment
        cls.student_with_class = CustomUser.objects.create_user(
            username='srtest_student_cls',
            password='password1!',
            email='wlhtestmails+srtest_student_cls@gmail.com',
        )
        _assign_role(cls.student_with_class, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student_with_class)

        # Create a classroom and enrol cls.student_with_class
        cls.classroom = ClassRoom.objects.create(
            name='Maths Class A',
            school=cls.school,
            is_active=True,
        )
        ClassStudent.objects.create(
            classroom=cls.classroom,
            student=cls.student_with_class,
            is_active=True,
        )

    # -- helpers --

    def _client_for(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _hub(self, client):
        """GET the student dashboard which renders base.html with the student sidebar.

        We use `student_dashboard` (progress app) rather than `subjects_hub`
        because `/hub/` renders `hub/home.html` with `hide_sidebar=True`, so the
        sidebar partial is not included in that response.  The student dashboard
        extends `base.html` without hiding the sidebar and accepts both school
        students and individual students.
        """
        return client.get(reverse('student_dashboard'))

    # -- test 1 --

    def test_student_sidebar_shows_my_progress(self):
        """Student sidebar must contain a 'My Progress' link."""
        client = self._client_for(self.student_no_class)
        resp = self._hub(client)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'My Progress')

    # -- test 2 --

    def test_student_sidebar_hides_homework_without_classes(self):
        """Student with no class enrolment should NOT see the Homework or Attendance
        sidebar links.

        The sidebar_student.html template gates both Homework and Attendance behind
        ``{% if student_has_classes and not is_individual_student %}``.

        Note: the bottom_nav.html always shows a Homework link for all students
        (mobile navigation), so we can't test for the homework URL in isolation.
        Instead we test for the Attendance link, which appears ONLY in the sidebar
        under the same condition and is absent from the bottom navigation.
        """
        client = self._client_for(self.student_no_class)
        resp = self._hub(client)
        self.assertEqual(resp.status_code, 200)
        # Attendance is only shown in the sidebar when student_has_classes is True.
        self.assertNotContains(resp, reverse('student_attendance_history'))

    # -- test 3 --

    def test_student_sidebar_shows_homework_with_classes(self):
        """Student with an active class enrolment should see Homework and Attendance in sidebar.

        sidebar_student.html gates both links behind
        ``{% if student_has_classes and not is_individual_student %}``.
        We use the Attendance URL as the unambiguous indicator because it appears
        only in the sidebar partial (not in the bottom_nav) — confirming that
        student_has_classes is True and the sidebar is rendering the full block.
        """
        client = self._client_for(self.student_with_class)
        resp = self._hub(client)
        self.assertEqual(resp.status_code, 200)
        # Attendance only appears in the sidebar when student_has_classes is True
        self.assertContains(resp, reverse('student_attendance_history'))
        # My Classes link also appears under the same condition
        self.assertContains(resp, reverse('student_my_classes'))


# ---------------------------------------------------------------------------
# 4: Individual student sidebar tests
# ---------------------------------------------------------------------------

class IndividualStudentSidebarTests(TestCase):
    """Tests for the individual_student sidebar."""

    @classmethod
    def setUpTestData(cls):
        cls.ind_student = CustomUser.objects.create_user(
            username='srtest_ind_student',
            password='password1!',
            email='wlhtestmails+srtest_ind_student@gmail.com',
        )
        _assign_role(cls.ind_student, Role.INDIVIDUAL_STUDENT)

        # TrialExpiryMiddleware redirects individual_student users who have no
        # subscription to the trial-expired page.  Create an active subscription
        # so the middleware lets the request through.
        pkg = Package.objects.create(
            name='Test Ind Package',
            price=Decimal('9.00'),
            stripe_price_id='',
            class_limit=1,
        )
        Subscription.objects.create(
            user=cls.ind_student,
            package=pkg,
            status=Subscription.STATUS_ACTIVE,
        )

    def test_individual_student_sidebar_hides_class_links(self):
        """individual_student role: My Classes, Join Class, Homework and Attendance absent."""
        client = Client()
        client.force_login(self.ind_student)
        # Use student_dashboard: extends base.html with sidebar visible.
        # /hub/ uses hide_sidebar=True so the sidebar is not rendered there.
        resp = client.get(reverse('student_dashboard'))
        self.assertEqual(resp.status_code, 200)

        # My Classes link — only rendered when student_has_classes AND not individual_student.
        # This link does NOT appear in the bottom_nav so the check is unambiguous.
        self.assertNotContains(resp, reverse('student_my_classes'))
        # Join Class — hidden for individual_student (not in bottom_nav either)
        self.assertNotContains(resp, reverse('student_join_class'))
        # Attendance — gated by same condition; not present in bottom_nav
        self.assertNotContains(resp, reverse('student_attendance_history'))
        # Note: we skip checking the homework URL because bottom_nav.html always
        # renders a Homework link for all student roles (mobile navigation), so a
        # URL-based check would produce a false positive here.


# ---------------------------------------------------------------------------
# 5: HoD sidebar test
# ---------------------------------------------------------------------------

class HodSidebarTests(TestCase):
    """Tests for the HoD sidebar (sidebar_hod.html)."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='srtest_hod_hoi',
            password='password1!',
            email='wlhtestmails+srtest_hod_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='srtest-hod-school')

        cls.hod_user = CustomUser.objects.create_user(
            username='srtest_hod_user',
            password='password1!',
            email='wlhtestmails+srtest_hod_user@gmail.com',
        )
        _assign_role(cls.hod_user, Role.HEAD_OF_DEPARTMENT)
        cls.dept = _setup_department(cls.school, head=cls.hod_user)

    def test_hod_sidebar_shown_for_hod_role(self):
        """HoD user's sidebar must contain the 'Classes' (Manage Classes) link."""
        client = Client()
        client.force_login(self.hod_user)
        resp = client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 200)
        # sidebar_hod.html contains a link to hod_manage_classes
        self.assertContains(resp, reverse('hod_manage_classes'))
        # And the department reports link
        self.assertContains(resp, reverse('hod_reports'))


# ---------------------------------------------------------------------------
# 6: Teacher sidebar test
# ---------------------------------------------------------------------------

class TeacherSidebarTests(TestCase):
    """Tests for the teacher sidebar (sidebar_teacher.html)."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='srtest_teacher_hoi',
            password='password1!',
            email='wlhtestmails+srtest_teacher_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='srtest-teacher-school')

        cls.teacher = CustomUser.objects.create_user(
            username='srtest_teacher',
            password='password1!',
            email='wlhtestmails+srtest_teacher@gmail.com',
        )
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.teacher,
            defaults={'role': 'teacher'},
        )

    def test_teacher_sidebar_shown_for_teacher_role(self):
        """Teacher user's sidebar must contain the teacher-specific 'My Classes' link (/hub/)
        and NOT the student 'My Classes' link (student_my_classes URL)."""
        client = Client()
        client.force_login(self.teacher)
        resp = client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)

        # sidebar_teacher.html links directly to /hub/
        self.assertContains(resp, '/hub/')
        # The teacher-specific 'My Classes' label (not the student enrollment path)
        self.assertContains(resp, 'My Classes')
        # The student "My Classes" URL (student_my_classes) must NOT appear here
        self.assertNotContains(resp, reverse('student_my_classes'))


# ---------------------------------------------------------------------------
# 7 & 8: Role switcher (topbar) tests
# ---------------------------------------------------------------------------

class RoleSwitcherTopbarTests(TestCase):
    """Tests for the role-switcher dropdown in the topbar."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='srtest_rs_hoi',
            password='password1!',
            email='wlhtestmails+srtest_rs_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='srtest-rs-school')

        # User with TWO roles: teacher + student
        cls.multi_role_user = CustomUser.objects.create_user(
            username='srtest_multirole',
            password='password1!',
            email='wlhtestmails+srtest_multirole@gmail.com',
        )
        _assign_role(cls.multi_role_user, Role.TEACHER)
        _assign_role(cls.multi_role_user, Role.STUDENT)
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.multi_role_user,
            defaults={'role': 'teacher'},
        )
        SchoolStudent.objects.create(school=cls.school, student=cls.multi_role_user)

        # User with a single role: teacher only
        cls.single_role_user = CustomUser.objects.create_user(
            username='srtest_singlerole',
            password='password1!',
            email='wlhtestmails+srtest_singlerole@gmail.com',
        )
        _assign_role(cls.single_role_user, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.single_role_user,
            defaults={'role': 'teacher'},
        )

    def test_role_switcher_present_for_multi_role_user(self):
        """User with 2 roles should see the role-switcher toggle in the topbar."""
        client = Client()
        client.force_login(self.multi_role_user)
        resp = client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)
        # topbar.html renders the switcher only when has_multiple_roles is True;
        # it renders a form with action="switch_role"
        self.assertContains(resp, reverse('switch_role'))
        # Also check the 'Switch Role' heading that appears inside the dropdown
        self.assertContains(resp, 'Switch Role')

    def test_role_switcher_absent_for_single_role_user(self):
        """User with only 1 role should NOT see the role-switcher in the topbar."""
        client = Client()
        client.force_login(self.single_role_user)
        resp = client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)
        # The switch_role form action should not appear
        self.assertNotContains(resp, reverse('switch_role'))


# ---------------------------------------------------------------------------
# 9: Role switching changes sidebar
# ---------------------------------------------------------------------------

class RoleSwitchingSidebarTests(TestCase):
    """Verify that POSTing to switch_role changes which sidebar is rendered."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='srtest_sw_hoi',
            password='password1!',
            email='wlhtestmails+srtest_sw_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school, cls.sub = _setup_school(cls.hoi, slug='srtest-sw-school')

        # User who is both HoD and Teacher
        cls.dual_user = CustomUser.objects.create_user(
            username='srtest_dual',
            password='password1!',
            email='wlhtestmails+srtest_dual@gmail.com',
        )
        _assign_role(cls.dual_user, Role.HEAD_OF_DEPARTMENT)
        _assign_role(cls.dual_user, Role.TEACHER)
        cls.dept = _setup_department(cls.school, head=cls.dual_user)
        # Also register as a teacher
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.dual_user,
            defaults={'role': 'teacher'},
        )

    def test_switching_role_changes_sidebar(self):
        """After switching from HoD to teacher role, teacher sidebar is shown, not HoD sidebar."""
        client = Client()
        client.force_login(self.dual_user)

        # By default the primary role will be HEAD_OF_DEPARTMENT (higher priority).
        # Confirm that HoD sidebar is shown first.
        resp_before = client.get(reverse('hod_overview'))
        self.assertEqual(resp_before.status_code, 200)
        self.assertContains(resp_before, reverse('hod_manage_classes'))

        # Now switch active role to 'teacher'
        switch_resp = client.post(
            reverse('switch_role'),
            {'role': Role.TEACHER},
        )
        # The switch view redirects somewhere after saving to session.
        self.assertIn(switch_resp.status_code, (302, 200))

        # After the switch, GET teacher_dashboard — it should render the teacher sidebar
        resp_after = client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp_after.status_code, 200)

        # Teacher sidebar contains /hub/ as My Classes
        self.assertContains(resp_after, '/hub/')
        # Teacher sidebar contains enrollment_requests link (teacher sidebar specific)
        self.assertContains(resp_after, reverse('enrollment_requests'))

        # HoD-specific links (hod_manage_classes) should NOT appear in the teacher sidebar
        self.assertNotContains(resp_after, reverse('hod_manage_classes'))
