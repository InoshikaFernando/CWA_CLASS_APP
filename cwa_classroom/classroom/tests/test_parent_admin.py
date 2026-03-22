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
            'hoi', 'hoi@test.com', 'pass1234',
        )
        cls.hoi_user.roles.add(cls.hoi_role)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.hoi_user,
        )

        cls.student = CustomUser.objects.create_user(
            'student1', 'student@test.com', 'pass1234',
            first_name='Zara', last_name='Student',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        cls.parent_a = CustomUser.objects.create_user(
            'parent_a', 'pa@test.com', 'pass1234',
            first_name='Alice', last_name='Parent',
        )
        cls.parent_a.roles.add(cls.parent_role)


class ParentInviteCreateViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='pass1234')

    def test_get_loads_form(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invite Parent')
        self.assertContains(resp, 'Zara Student')

    def test_post_creates_invite(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.post(url, {
            'parent_email': 'newparent@test.com',
            'relationship': 'mother',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ParentInvite.objects.filter(
                parent_email='newparent@test.com',
                student=self.student,
                status='pending',
            ).exists()
        )

    def test_post_blocks_third_parent(self):
        """Cannot invite when student already has 2 active parents."""
        parent_b = CustomUser.objects.create_user('pb', 'pb@t.com', 'pass1234')
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student, school=self.school,
        )
        ParentStudent.objects.create(
            parent=parent_b, student=self.student, school=self.school,
        )
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.post(url, {
            'parent_email': 'third@test.com',
            'relationship': 'guardian',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ParentInvite.objects.filter(parent_email='third@test.com').exists()
        )

    def test_post_blocks_duplicate_pending_invite(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        self.client.post(url, {'parent_email': 'dup@test.com'})
        self.client.post(url, {'parent_email': 'dup@test.com'})
        count = ParentInvite.objects.filter(parent_email='dup@test.com').count()
        self.assertEqual(count, 1)

    def test_invalid_email_rejected(self):
        url = reverse('invite_parent', args=[self.school.id, self.student.id])
        resp = self.client.post(url, {'parent_email': 'bademail'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ParentInvite.objects.count(), 0)

    def test_requires_hoi_role(self):
        self.client.login(username='student1', password='pass1234')
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
        self.client.login(username='hoi', password='pass1234')

    def test_list_loads(self):
        ParentInvite.objects.create(
            school=self.school, student=self.student,
            parent_email='test@test.com', invited_by=self.hoi_user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        url = reverse('parent_invite_list', args=[self.school.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'test@test.com')

    def test_empty_list(self):
        url = reverse('parent_invite_list', args=[self.school.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No parent invites')


class ParentInviteRevokeViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='pass1234')

    def test_revoke_pending_invite(self):
        invite = ParentInvite.objects.create(
            school=self.school, student=self.student,
            parent_email='rev@test.com', invited_by=self.hoi_user,
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
            parent_email='acc@test.com', invited_by=self.hoi_user,
            expires_at=timezone.now() + timedelta(days=7),
            status='accepted',
        )
        url = reverse('revoke_parent_invite', args=[self.school.id, invite.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)


class StudentParentLinksViewTest(ParentAdminTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='pass1234')

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
        self.client.login(username='hoi', password='pass1234')

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
