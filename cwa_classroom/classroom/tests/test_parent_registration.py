from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, ParentStudent, ParentInvite,
)


class ParentRegistrationTestBase(TestCase):
    """Shared fixtures for parent registration tests."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        cls.admin_user = CustomUser.objects.create_user(
            'admin', 'admin@test.com', 'pass1234',
            first_name='Admin', last_name='User',
        )
        cls.admin_user.roles.add(cls.admin_role)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )

        cls.student = CustomUser.objects.create_user(
            'student1', 'student@test.com', 'pass1234',
            first_name='Zara', last_name='Student',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

    def _make_invite(self, **kwargs):
        defaults = {
            'school': self.school,
            'student': self.student,
            'parent_email': 'newparent@test.com',
            'invited_by': self.admin_user,
            'expires_at': timezone.now() + timedelta(days=7),
        }
        defaults.update(kwargs)
        return ParentInvite.objects.create(**defaults)


class ParentRegisterViewTest(ParentRegistrationTestBase):
    """Test the parent registration form (new account via invite token)."""

    def setUp(self):
        self.client = Client()
        self.invite = self._make_invite()

    def test_get_shows_registration_form(self):
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Register as Parent')
        self.assertContains(resp, 'Zara Student')
        self.assertContains(resp, 'Test School')

    def test_get_prefills_email(self):
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.get(url)
        self.assertContains(resp, 'newparent@test.com')

    def test_post_creates_user_and_links(self):
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'newparent@test.com',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)

        # User created with PARENT role
        user = CustomUser.objects.get(email='newparent@test.com')
        self.assertTrue(user.is_parent)
        self.assertEqual(user.first_name, 'Jane')

        # ParentStudent link created
        link = ParentStudent.objects.get(parent=user, student=self.student)
        self.assertEqual(link.school, self.school)
        self.assertTrue(link.is_active)

        # Invite marked accepted
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.status, 'accepted')
        self.assertIsNotNone(self.invite.accepted_at)
        self.assertEqual(self.invite.accepted_by, user)

    def test_post_auto_generates_username(self):
        url = reverse('register_parent', args=[self.invite.token])
        self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'newparent@test.com',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
            'accept_terms': 'on',
        })
        user = CustomUser.objects.get(email='newparent@test.com')
        self.assertTrue(user.username.startswith('newparent'))

    def test_post_user_is_logged_in(self):
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'newparent@test.com',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
            'accept_terms': 'on',
        }, follow=True)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_post_validation_errors(self):
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.post(url, {
            'first_name': '',
            'last_name': '',
            'email': 'newparent@test.com',
            'password': 'short',
            'confirm_password': 'mismatch',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'First name is required')

    def test_post_duplicate_email_shows_error(self):
        # Create a user with same email first
        CustomUser.objects.create_user('existing', 'newparent@test.com', 'pass1234')
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'newparent@test.com',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_expired_invite_shows_error(self):
        invite = self._make_invite(
            parent_email='expired@test.com',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        url = reverse('register_parent', args=[invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'expired')

    def test_accepted_invite_shows_error(self):
        invite = self._make_invite(
            parent_email='used@test.com',
            status='accepted',
        )
        url = reverse('register_parent', args=[invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already been used')

    def test_revoked_invite_shows_error(self):
        invite = self._make_invite(
            parent_email='revoked@test.com',
            status='revoked',
        )
        url = reverse('register_parent', args=[invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'revoked')

    def test_logged_in_user_redirected_to_accept_invite(self):
        self.client.login(username='admin', password='pass1234')
        url = reverse('register_parent', args=[self.invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('accept-invite', resp.url)

    def test_invalid_token_returns_404(self):
        import uuid
        url = reverse('register_parent', args=[uuid.uuid4()])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_post_on_expired_invite_shows_error(self):
        invite = self._make_invite(
            parent_email='late@test.com',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        url = reverse('register_parent', args=[invite.token])
        resp = self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'late@test.com',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CustomUser.objects.filter(email='late@test.com').exists())


class ParentAcceptInviteViewTest(ParentRegistrationTestBase):
    """Test the accept-invite flow for existing logged-in users."""

    def setUp(self):
        self.client = Client()
        self.existing_user = CustomUser.objects.create_user(
            'existingparent', 'existing@test.com', 'pass1234',
            first_name='Existing', last_name='Parent',
        )
        self.invite = self._make_invite(parent_email='existing@test.com')

    def test_requires_login(self):
        url = reverse('accept_parent_invite', args=[self.invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_get_shows_confirmation(self):
        self.client.login(username='existingparent', password='pass1234')
        url = reverse('accept_parent_invite', args=[self.invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Accept Parent Invite')
        self.assertContains(resp, 'Zara Student')

    def test_post_creates_link_and_adds_role(self):
        self.client.login(username='existingparent', password='pass1234')
        url = reverse('accept_parent_invite', args=[self.invite.token])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        # PARENT role added
        self.existing_user.refresh_from_db()
        self.assertTrue(self.existing_user.is_parent)

        # ParentStudent link created
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=self.existing_user, student=self.student,
            ).exists()
        )

        # Invite marked accepted
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.status, 'accepted')

    def test_post_does_not_duplicate_parent_role(self):
        """If user already has PARENT role, don't create a duplicate UserRole."""
        self.existing_user.roles.add(self.parent_role)
        self.client.login(username='existingparent', password='pass1234')
        url = reverse('accept_parent_invite', args=[self.invite.token])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        role_count = UserRole.objects.filter(
            user=self.existing_user, role=self.parent_role,
        ).count()
        self.assertEqual(role_count, 1)

    def test_second_child_link(self):
        """Existing parent accepts invite for a second child."""
        self.existing_user.roles.add(self.parent_role)
        # First child already linked
        ParentStudent.objects.create(
            parent=self.existing_user, student=self.student,
            school=self.school,
        )

        # Second child
        student_b = CustomUser.objects.create_user(
            'student_b', 'sb@test.com', 'pass1234',
            first_name='Yuki', last_name='Student',
        )
        student_b.roles.add(self.student_role)
        invite_b = self._make_invite(
            parent_email='existing@test.com',
            student=student_b,
        )

        self.client.login(username='existingparent', password='pass1234')
        url = reverse('accept_parent_invite', args=[invite_b.token])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        links = ParentStudent.objects.filter(parent=self.existing_user)
        self.assertEqual(links.count(), 2)

    def test_expired_invite_rejected(self):
        invite = self._make_invite(
            parent_email='existing@test.com',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.client.login(username='existingparent', password='pass1234')
        url = reverse('accept_parent_invite', args=[invite.token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)


class ParentRegistrationURLTest(TestCase):
    """Test URL resolution for parent registration routes."""

    def test_register_parent_url_resolves(self):
        import uuid
        url = reverse('register_parent', args=[uuid.uuid4()])
        self.assertIn('/accounts/register/parent/', url)

    def test_accept_invite_url_resolves(self):
        import uuid
        url = reverse('accept_parent_invite', args=[uuid.uuid4()])
        self.assertIn('/accounts/accept-invite/', url)
