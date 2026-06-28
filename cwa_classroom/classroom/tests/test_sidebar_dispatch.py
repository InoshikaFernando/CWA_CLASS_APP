"""
Regression tests pinning *which* sidebar partial base.html dispatches to,
across pages — guarding the reported "different sidebars load unexpectedly"
instability from recurring.

The sidebar is chosen server-side in ``base.html`` from two independent inputs:

  1. the active **role** (``is_student``, ``is_teacher``, ...), and
  2. the URL-derived **subject_sidebar** (set by the subject-plugin registry).

The design intent (see ``sidebar_student.html``) is that students get ONE
unified sidebar that adapts its links inline — it must NOT structurally switch
to a different partial as the student moves between hub / maths / worksheet /
homework pages. The single deliberate exception is Coding, which renders the
separate ``sidebar_coding.html``.

To make "which partial rendered" unambiguous and resilient to link/label
changes, each dispatched student partial emits a stable HTML marker:

    <!-- sidebar-variant:student -->   (sidebar_student.html)
    <!-- sidebar-variant:coding -->    (sidebar_coding.html)

These tests assert the marker per (role, path). If someone reintroduces a
separate maths sidebar, or coding stops switching, the marker assertion fails.

Plain Django ``Client`` tests (no Playwright) — response HTML is sufficient.

Run with:
    python manage.py test classroom.tests.test_sidebar_dispatch
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School,
    SchoolStudent,
    SchoolTeacher,
    ClassRoom,
    ClassStudent,
)

STUDENT_MARKER = "<!-- sidebar-variant:student -->"
CODING_MARKER = "<!-- sidebar-variant:coding -->"
TEACHER_MARKER = "<!-- sidebar-variant:teacher -->"


def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    UserRole.objects.get_or_create(user=user, role=_create_role(role_name))


def _setup_school(admin_user, slug):
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
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return school


class StudentSidebarDispatchTests(TestCase):
    """The student sidebar partial must stay the SAME (unified) across the
    dashboard, maths, and worksheet pages — and only switch to the coding
    partial on /coding/ pages."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sbd_hoi',
            password='password1!',
            email='wlhtestmails+sbd_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school = _setup_school(cls.hoi, slug='sbd-school')

        cls.student = CustomUser.objects.create_user(
            username='sbd_student',
            password='password1!',
            email='wlhtestmails+sbd_student@gmail.com',
        )
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        cls.classroom = ClassRoom.objects.create(
            name='Maths Class A', school=cls.school, is_active=True,
        )
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.student)

    def test_dashboard_uses_unified_student_sidebar(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, STUDENT_MARKER)
        self.assertNotContains(resp, CODING_MARKER)

    def test_maths_page_does_not_switch_sidebar(self):
        """On a maths page the SAME unified student sidebar must render —
        not a separate maths partial. This is the core anti-drift guard."""
        resp = self.client.get(reverse('maths:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, STUDENT_MARKER)
        self.assertNotContains(resp, CODING_MARKER)

    def test_coding_page_uses_coding_sidebar(self):
        """Coding is the single deliberate exception — it switches partials."""
        resp = self.client.get(reverse('coding:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, CODING_MARKER)
        self.assertNotContains(resp, STUDENT_MARKER)

    def test_hub_renders_the_student_sidebar(self):
        """The hub/home page must show the unified sidebar like every other
        student page (it previously hid it)."""
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, STUDENT_MARKER)
        self.assertNotContains(resp, CODING_MARKER)

    def test_worksheet_list_keeps_subject_context_via_query_param(self):
        """A maths-filtered worksheet list keeps the maths subject context
        (and therefore the maths sidebar section) even though it lives outside
        the /maths/ URL prefix — via the ?subject=mathematics convention."""
        resp = self.client.get(
            reverse('worksheets:student_list'), {'subject': 'mathematics'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['subject_sidebar'], 'maths')
        # Still the unified student sidebar — no structural switch.
        self.assertContains(resp, STUDENT_MARKER)
        self.assertNotContains(resp, CODING_MARKER)


class SidebarDesktopMobileAgreementTests(TestCase):
    """The desktop sidebar and the mobile drawer both render the role→sidebar
    dispatch. They must agree on the variant — never one variant on desktop and
    a different one in the mobile drawer (the drift this fix removed).

    Each page therefore emits the SAME variant marker twice (desktop + mobile)
    and never mixes the two variants.
    """

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sbd2_hoi',
            password='password1!',
            email='wlhtestmails+sbd2_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school = _setup_school(cls.hoi, slug='sbd2-school')

        cls.student = CustomUser.objects.create_user(
            username='sbd2_student',
            password='password1!',
            email='wlhtestmails+sbd2_student@gmail.com',
        )
        _assign_role(cls.student, Role.STUDENT)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.student)

    def test_non_subject_page_agrees_on_student_variant(self):
        body = self.client.get(reverse('student_dashboard')).content.decode()
        self.assertEqual(body.count(CODING_MARKER), 0)
        self.assertGreaterEqual(
            body.count(STUDENT_MARKER), 2,
            'Both desktop sidebar and mobile drawer should render the student variant',
        )

    def test_coding_page_agrees_on_coding_variant(self):
        """Desktop AND mobile drawer must both switch to coding on /coding/ —
        previously the mobile drawer kept showing the student sidebar."""
        body = self.client.get(reverse('coding:home')).content.decode()
        self.assertEqual(body.count(STUDENT_MARKER), 0)
        self.assertGreaterEqual(
            body.count(CODING_MARKER), 2,
            'Both desktop sidebar and mobile drawer should render the coding variant',
        )


class TeacherSidebarDispatchTests(TestCase):
    """Non-student roles get a single, stable sidebar across all their pages,
    with desktop and mobile in agreement — and the student-only coding swap
    can never leak in (teachers are redirected away from student subject
    pages, so they never render a student/coding sidebar at all).
    """

    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user(
            username='sbd3_hoi',
            password='password1!',
            email='wlhtestmails+sbd3_hoi@gmail.com',
        )
        _assign_role(cls.hoi, Role.HEAD_OF_INSTITUTE)
        cls.school = _setup_school(cls.hoi, slug='sbd3-school')

        cls.teacher = CustomUser.objects.create_user(
            username='sbd3_teacher',
            password='password1!',
            email='wlhtestmails+sbd3_teacher@gmail.com',
        )
        _assign_role(cls.teacher, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.teacher,
            defaults={'role': 'teacher'},
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.teacher)

    def _assert_teacher_variant(self, url_name):
        body = self.client.get(reverse(url_name)).content.decode()
        self.assertEqual(body.count(STUDENT_MARKER), 0)
        self.assertEqual(body.count(CODING_MARKER), 0)
        self.assertGreaterEqual(
            body.count(TEACHER_MARKER), 2,
            'Desktop sidebar and mobile drawer should both render the teacher variant',
        )

    def test_dashboard_uses_teacher_sidebar(self):
        self._assert_teacher_variant('teacher_dashboard')

    def test_enrollment_page_uses_teacher_sidebar(self):
        """Same teacher sidebar on a second teacher page — it stays stable
        across pages, never switching."""
        self._assert_teacher_variant('enrollment_requests')

    def test_teacher_is_redirected_from_student_subject_pages(self):
        """A teacher visiting a student subject URL (/coding/) is redirected
        to their own area — they never get a student or coding sidebar."""
        resp = self.client.get(reverse('coding:home'))
        self.assertEqual(resp.status_code, 302)
