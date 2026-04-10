"""
Tests for school picker views (multi-school selection) and the
sidebar_pending_parent_requests context processor badge.
"""
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, SchoolTeacher,
    ParentLinkRequest, ParentStudent,
)


class SchoolPickerTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'},
        )
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )

        # HoI who owns two schools
        cls.hoi = CustomUser.objects.create_user(
            'picker_hoi', 'wlhtestmails+picker_hoi@gmail.com', 'password1!',
        )
        cls.hoi.roles.add(cls.hoi_role)

        cls.school_a = School.objects.create(
            name='School Alpha', slug='school-alpha-pk', admin=cls.hoi,
        )
        cls.school_b = School.objects.create(
            name='School Beta', slug='school-beta-pk', admin=cls.hoi,
        )

        # Teacher in a single school
        cls.single_teacher = CustomUser.objects.create_user(
            'picker_teacher', 'wlhtestmails+picker_teacher@gmail.com', 'password1!',
        )
        cls.single_teacher.roles.add(cls.hoi_role)
        cls.single_school = School.objects.create(
            name='Single School', slug='single-school-pk', admin=cls.single_teacher,
        )

        # Student for search tests
        cls.student = CustomUser.objects.create_user(
            'picker_student', 'wlhtestmails+picker_student@gmail.com', 'password1!',
            first_name='Zara', last_name='Picker',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school_a, student=cls.student)


# ---------------------------------------------------------------------------
# ManageTeachersRedirectView (school picker for teachers)
# ---------------------------------------------------------------------------

class TeachersPickerViewTest(SchoolPickerTestBase):

    def setUp(self):
        self.client = Client()

    def test_multi_school_hoi_sees_picker(self):
        self.client.login(username='picker_hoi', password='password1!')
        resp = self.client.get(reverse('admin_select_school_teachers'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'School Alpha')
        self.assertContains(resp, 'School Beta')

    def test_single_school_hoi_redirects_directly(self):
        self.client.login(username='picker_teacher', password='password1!')
        resp = self.client.get(reverse('admin_select_school_teachers'))
        self.assertRedirects(
            resp,
            reverse('admin_school_teachers', args=[self.single_school.id]),
            fetch_redirect_response=False,
        )

    def test_requires_login(self):
        resp = self.client.get(reverse('admin_select_school_teachers'))
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# ManageStudentsRedirectView (school picker for students)
# ---------------------------------------------------------------------------

class StudentsPickerViewTest(SchoolPickerTestBase):

    def setUp(self):
        self.client = Client()

    def test_multi_school_hoi_sees_picker(self):
        self.client.login(username='picker_hoi', password='password1!')
        resp = self.client.get(reverse('admin_select_school_students'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'School Alpha')
        self.assertContains(resp, 'School Beta')

    def test_single_school_hoi_redirects_directly(self):
        self.client.login(username='picker_teacher', password='password1!')
        resp = self.client.get(reverse('admin_select_school_students'))
        self.assertRedirects(
            resp,
            reverse('admin_school_students', args=[self.single_school.id]),
            fetch_redirect_response=False,
        )

    def test_superuser_sees_student_search_section(self):
        su = CustomUser.objects.create_superuser(
            'picker_su', 'wlhtestmails+picker_su@gmail.com', 'password1!',
        )
        # Give superuser two schools to see picker
        School.objects.create(name='SU School A', slug='su-school-a-pk', admin=su)
        School.objects.create(name='SU School B', slug='su-school-b-pk', admin=su)
        self.client.login(username='picker_su', password='password1!')
        resp = self.client.get(reverse('admin_select_school_students'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Search Individual Student')


# ---------------------------------------------------------------------------
# ManageParentsRedirectView (school picker for parents)
# ---------------------------------------------------------------------------

class ParentsPickerViewTest(SchoolPickerTestBase):

    def setUp(self):
        self.client = Client()

    def test_multi_school_hoi_sees_picker(self):
        self.client.login(username='picker_hoi', password='password1!')
        resp = self.client.get(reverse('admin_select_school_parents'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'School Alpha')
        self.assertContains(resp, 'School Beta')

    def test_single_school_hoi_redirects_directly(self):
        self.client.login(username='picker_teacher', password='password1!')
        resp = self.client.get(reverse('admin_select_school_parents'))
        self.assertRedirects(
            resp,
            reverse('admin_school_parents', args=[self.single_school.id]),
            fetch_redirect_response=False,
        )


# ---------------------------------------------------------------------------
# StudentSearchView (HTMX endpoint)
# ---------------------------------------------------------------------------

class StudentSearchViewTest(SchoolPickerTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='picker_hoi', password='password1!')
        self.url = reverse('htmx_student_search')

    def test_short_query_returns_empty(self):
        resp = self.client.get(self.url, {'q': 'Z'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Zara')

    def test_matching_query_returns_student(self):
        resp = self.client.get(self.url, {'q': 'Zara'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Zara')

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(self.url, {'q': 'Zara'})
        self.assertNotEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# sidebar_pending_parent_requests context processor badge
# ---------------------------------------------------------------------------

class SidebarParentRequestsBadgeTest(SchoolPickerTestBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # HoI needs a SchoolTeacher membership to appear in _get_teacher_schools
        SchoolTeacher.objects.get_or_create(
            school=cls.school_a, teacher=cls.hoi,
            defaults={'role': 'head_of_institute', 'is_active': True},
        )
        # A parent with a pending link request
        cls.parent = CustomUser.objects.create_user(
            'badge_parent', 'wlhtestmails+badge_parent@gmail.com', 'password1!',
        )
        cls.parent.roles.add(cls.parent_role)
        cls.school_student = SchoolStudent.objects.get(
            school=cls.school_a, student=cls.student,
        )
        cls.pending_req = ParentLinkRequest.objects.create(
            parent=cls.parent,
            school_student=cls.school_student,
            relationship='mother',
            status=ParentLinkRequest.STATUS_PENDING,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='picker_hoi', password='password1!')

    def test_badge_count_in_context(self):
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.context.get('sidebar_pending_parent_requests'), 1)

    def test_badge_zero_when_no_pending(self):
        self.pending_req.status = ParentLinkRequest.STATUS_APPROVED
        self.pending_req.save(update_fields=['status'])
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.context.get('sidebar_pending_parent_requests'), 0)
        # Restore for other tests
        self.pending_req.status = ParentLinkRequest.STATUS_PENDING
        self.pending_req.save(update_fields=['status'])

    def test_parent_link_requests_page_accessible_to_hoi(self):
        resp = self.client.get(reverse('parent_link_requests'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'badge_parent')
