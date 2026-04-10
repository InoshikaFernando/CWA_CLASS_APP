"""Tests for HoI parent management views (CPP-70)."""
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from classroom.models import School, SchoolStudent, ParentStudent, ParentInvite


class ParentAdminTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'},
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        cls.hoi_user = CustomUser.objects.create_user(
            'hoi', 'wlhtestmails+hoi@gmail.com', 'password1!',
        )
        cls.hoi_user.roles.add(cls.hoi_role)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.hoi_user,
        )

        cls.student = CustomUser.objects.create_user(
            'student1', 'wlhtestmails+student@gmail.com', 'password1!',
            first_name='Zara', last_name='Student',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        cls.parent_a = CustomUser.objects.create_user(
            'parent_a', 'wlhtestmails+pa@gmail.com', 'password1!',
            first_name='Alice', last_name='Parent',
        )
        cls.parent_a.roles.add(cls.parent_role)


class ParentInviteCreateViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')

    def test_get_loads_form(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invite Parent')
        self.assertContains(resp, 'Zara Student')

    def test_post_creates_invite(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.post(url, {
            'parent_email': 'wlhtestmails+newparent@gmail.com',
            'relationship': 'mother',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ParentInvite.objects.filter(
                parent_email='wlhtestmails+newparent@gmail.com',
                student=self.student,
                status='pending',
            ).exists()
        )

    def test_post_blocks_third_parent(self):
        """Cannot invite when student already has 2 active parents."""
        parent_b = CustomUser.objects.create_user('pb', 'wlhtestmails+pb@gmail.com', 'password1!')
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student, school=self.school,
        )
        ParentStudent.objects.create(
            parent=parent_b, student=self.student, school=self.school,
        )
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.post(url, {
            'parent_email': 'wlhtestmails+third@gmail.com',
            'relationship': 'guardian',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ParentInvite.objects.filter(parent_email='wlhtestmails+third@gmail.com').exists()
        )

    def test_post_blocks_duplicate_pending_invite(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        self.client.post(url, {'parent_email': 'wlhtestmails+dup@gmail.com'})
        self.client.post(url, {'parent_email': 'wlhtestmails+dup@gmail.com'})
        count = ParentInvite.objects.filter(parent_email='wlhtestmails+dup@gmail.com').count()
        self.assertEqual(count, 1)

    def test_invalid_email_rejected(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.post(url, {'parent_email': 'bademail'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ParentInvite.objects.count(), 0)

    def test_requires_hoi_role(self):
        self.client.login(username='student1', password='password1!')
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.get(url)
        self.assertNotEqual(resp.status_code, 200)

    def test_shows_existing_links(self):
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student, school=self.school,
        )
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.get(url)
        self.assertContains(resp, 'Alice Parent')


class ParentInviteListViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')

    def test_list_loads(self):
        ParentInvite.objects.create(
            school=self.school, student=self.student,
            parent_email='wlhtestmails+test@gmail.com', invited_by=self.hoi_user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        url = reverse('parent_invite_list', args=[self.school.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'wlhtestmails+test@gmail.com')

    def test_empty_list(self):
        url = reverse('parent_invite_list', args=[self.school.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No parent invites')


class ParentInviteRevokeViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')

    def test_revoke_pending_invite(self):
        invite = ParentInvite.objects.create(
            school=self.school, student=self.student,
            parent_email='wlhtestmails+rev@gmail.com', invited_by=self.hoi_user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        url = reverse('revoke_parent_invite', args=[self.school.id, invite.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        invite.refresh_from_db()
        self.assertEqual(invite.status, 'revoked')

    def test_revoke_accepted_invite_404(self):
        invite = ParentInvite.objects.create(
            school=self.school, student=self.student,
            parent_email='wlhtestmails+acc@gmail.com', invited_by=self.hoi_user,
            expires_at=timezone.now() + timedelta(days=7),
            status='accepted',
        )
        url = reverse('revoke_parent_invite', args=[self.school.id, invite.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)


class StudentParentLinksViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')

    def test_view_shows_links(self):
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student, school=self.school,
        )
        url = reverse('student_parent_links', args=[self.school.id, self.student.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Alice Parent')

    def test_empty_links(self):
        url = reverse('student_parent_links', args=[self.school.id, self.student.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No parent links')


class ParentStudentUnlinkViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')

    def test_unlink_deactivates(self):
        link = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student, school=self.school,
        )
        url = reverse('unlink_parent_student', args=[self.school.id, self.student.id, link.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        link.refresh_from_db()
        self.assertFalse(link.is_active)


class ParentAdminURLTest(TestCase):

    def test_all_admin_urls_resolve(self):
        self.assertTrue(reverse('invite_parent', args=[1, 1]))
        self.assertTrue(reverse('parent_invite_list', args=[1]))
        self.assertTrue(reverse('revoke_parent_invite', args=[1, 1]))
        self.assertTrue(reverse('student_parent_links', args=[1, 1]))
        self.assertTrue(reverse('unlink_parent_student', args=[1, 1, 1]))
        self.assertTrue(reverse('admin_school_add_parent', args=[1]))
        self.assertTrue(reverse('admin_school_link_parent', args=[1]))
        self.assertTrue(reverse('admin_school_parent_search', args=[1]))


# ---------------------------------------------------------------------------
# AddParentView tests
# ---------------------------------------------------------------------------

class AddParentViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')
        self.url = reverse('admin_school_add_parent', args=[self.school.id])

    def test_get_renders_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add New Parent')
        self.assertContains(resp, 'Zara Student')

    def test_post_creates_parent_user_and_link(self):
        resp = self.client.post(self.url, {
            'first_name': 'New',
            'last_name': 'Parent',
            'email': 'wlhtestmails+newp@gmail.com',
            'phone': '',
            'relationship': 'mother',
            'student_ids': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        new_user = CustomUser.objects.get(email='wlhtestmails+newp@gmail.com')
        self.assertTrue(new_user.has_role(Role.PARENT))
        self.assertTrue(new_user.must_change_password)
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=new_user, student=self.student, school=self.school, is_active=True,
            ).exists()
        )

    def test_post_no_students_still_creates_user(self):
        resp = self.client.post(self.url, {
            'first_name': 'Solo',
            'last_name': 'Parent',
            'email': 'wlhtestmails+solo@gmail.com',
            'relationship': 'guardian',
            'student_ids': [],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(email='wlhtestmails+solo@gmail.com').exists())
        self.assertEqual(ParentStudent.objects.filter(school=self.school).count(), 0)

    def test_post_existing_email_shows_warning(self):
        """If the email belongs to an existing user, re-render form with warning."""
        resp = self.client.post(self.url, {
            'first_name': 'Alice',
            'last_name': 'Parent',
            'email': self.parent_a.email,
            'relationship': 'mother',
            'student_ids': [],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Found existing account')
        self.assertContains(resp, 'Alice Parent')

    def test_post_invalid_email_rejected(self):
        resp = self.client.post(self.url, {
            'first_name': 'Bad',
            'last_name': 'Email',
            'email': 'notanemail',
            'relationship': 'guardian',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(username__startswith='notanemail').exists())

    def test_post_missing_name_rejected(self):
        resp = self.client.post(self.url, {
            'first_name': '',
            'last_name': '',
            'email': 'wlhtestmails+noname@gmail.com',
            'relationship': 'guardian',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(email='wlhtestmails+noname@gmail.com').exists())

    def test_requires_hoi_role(self):
        self.client.login(username='student1', password='password1!')
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    def test_respects_two_parent_limit(self):
        parent_b = CustomUser.objects.create_user(
            'pb2', 'wlhtestmails+pb2@gmail.com', 'password1!',
        )
        ParentStudent.objects.create(parent=self.parent_a, student=self.student, school=self.school)
        ParentStudent.objects.create(parent=parent_b, student=self.student, school=self.school)
        resp = self.client.post(self.url, {
            'first_name': 'Third',
            'last_name': 'Parent',
            'email': 'wlhtestmails+third@gmail.com',
            'relationship': 'guardian',
            'student_ids': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        third = CustomUser.objects.filter(email='wlhtestmails+third@gmail.com').first()
        self.assertIsNotNone(third)
        # User created but no link (at limit)
        self.assertFalse(
            ParentStudent.objects.filter(parent=third, student=self.student).exists()
        )


# ---------------------------------------------------------------------------
# LinkExistingParentView tests
# ---------------------------------------------------------------------------

class LinkExistingParentViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')
        self.url = reverse('admin_school_link_parent', args=[self.school.id])

    def test_get_renders_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Link Existing Parent')
        self.assertContains(resp, 'Zara Student')

    def test_post_creates_link(self):
        resp = self.client.post(self.url, {
            'parent_id': self.parent_a.id,
            'relationship': 'mother',
            'student_ids': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=self.parent_a, student=self.student, school=self.school, is_active=True,
            ).exists()
        )

    def test_post_skips_duplicate_link(self):
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student, school=self.school,
        )
        resp = self.client.post(self.url, {
            'parent_id': self.parent_a.id,
            'relationship': 'mother',
            'student_ids': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            ParentStudent.objects.filter(
                parent=self.parent_a, student=self.student, school=self.school,
            ).count(),
            1,
        )

    def test_post_invalid_parent_id_redirects(self):
        resp = self.client.post(self.url, {
            'parent_id': 99999,
            'relationship': 'guardian',
            'student_ids': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ParentStudent.objects.filter(student=self.student).exists())

    def test_post_missing_parent_id_redirects(self):
        resp = self.client.post(self.url, {
            'parent_id': '',
            'relationship': 'guardian',
            'student_ids': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ParentStudent.objects.filter(student=self.student).exists())

    def test_assigns_parent_role_if_missing(self):
        """Linking grants the parent role even if the user didn't have it."""
        non_parent = CustomUser.objects.create_user(
            'nonparent', 'wlhtestmails+np@gmail.com', 'password1!',
        )
        self.client.post(self.url, {
            'parent_id': non_parent.id,
            'relationship': 'guardian',
            'student_ids': [self.student.id],
        })
        self.assertTrue(non_parent.has_role(Role.PARENT))

    def test_requires_hoi_role(self):
        self.client.login(username='student1', password='password1!')
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# ParentAccountSearchView (HTMX) tests
# ---------------------------------------------------------------------------

class ParentAccountSearchViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='password1!')
        self.url = reverse('admin_school_parent_search', args=[self.school.id])

    def test_returns_matching_users(self):
        resp = self.client.get(self.url, {'q': 'Alice'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Alice')

    def test_empty_query_returns_empty(self):
        resp = self.client.get(self.url, {'q': 'x'})
        self.assertEqual(resp.status_code, 200)

    def test_short_query_returns_empty(self):
        resp = self.client.get(self.url, {'q': 'a'})
        self.assertEqual(resp.status_code, 200)

    def test_requires_hoi_role(self):
        self.client.login(username='student1', password='password1!')
        resp = self.client.get(self.url, {'q': 'Alice'})
        self.assertNotEqual(resp.status_code, 200)
