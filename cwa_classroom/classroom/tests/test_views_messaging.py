"""
Unit tests for classroom/views_messaging.py (CPP-349).

Covers: URL resolution, access control, redirect behaviour, and HTTP status codes
for MessagingDashboardView and MessagingComposeView.
"""
from django.test import TestCase, Client
from django.urls import reverse, resolve

from accounts.models import CustomUser, Role, UserRole
from classroom.models import School


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)


def _make_user(username, email, role_name=None, password='Testpass1!'):
    user = CustomUser.objects.create_user(
        username=username, password=password, email=email,
    )
    if role_name:
        _assign_role(user, role_name)
    return user


def _make_admin_with_school():
    user = _make_user('admin_msg', 'wlhtestmails+admin_msg@gmail.com', Role.ADMIN)
    school = School.objects.create(name='Msg Test School', slug='msg-test-school', admin=user)
    return user, school


# ---------------------------------------------------------------------------
# URL resolution tests
# ---------------------------------------------------------------------------

class TestMessagingURLs(TestCase):
    """URL names resolve to correct paths and views."""

    def test_messaging_dashboard_url_reverses(self):
        url = reverse('messaging_dashboard')
        self.assertEqual(url, '/admin-dashboard/messaging/')

    def test_messaging_compose_url_reverses(self):
        url = reverse('messaging_compose')
        self.assertEqual(url, '/admin-dashboard/messaging/compose/')

    def test_messaging_dashboard_resolves_to_view(self):
        resolved = resolve('/admin-dashboard/messaging/')
        self.assertEqual(resolved.url_name, 'messaging_dashboard')

    def test_messaging_compose_resolves_to_view(self):
        resolved = resolve('/admin-dashboard/messaging/compose/')
        self.assertEqual(resolved.url_name, 'messaging_compose')


# ---------------------------------------------------------------------------
# MessagingDashboardView — /admin-dashboard/messaging/
# ---------------------------------------------------------------------------

class TestMessagingDashboardView(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('messaging_dashboard')

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_admin_role_redirects_to_compose(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)

    def test_institute_owner_redirects_to_compose(self):
        user = _make_user('owner_msg', 'wlhtestmails+owner_msg@gmail.com', Role.INSTITUTE_OWNER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)

    def test_head_of_institute_redirects_to_compose(self):
        user = _make_user('hoi_msg', 'wlhtestmails+hoi_msg@gmail.com', Role.HEAD_OF_INSTITUTE)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)

    def test_student_role_denied(self):
        user = _make_user('student_msg', 'wlhtestmails+student_msg@gmail.com', Role.STUDENT)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_teacher_role_denied(self):
        user = _make_user('teacher_msg', 'wlhtestmails+teacher_msg@gmail.com', Role.TEACHER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_superuser_redirects_to_compose(self):
        user = CustomUser.objects.create_superuser(
            username='super_msg', password='Testpass1!', email='wlhtestmails+super_msg@gmail.com',
        )
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('messaging_compose'), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# MessagingComposeView — /admin-dashboard/messaging/compose/
# ---------------------------------------------------------------------------

class TestMessagingComposeView(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('messaging_compose')

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_admin_role_returns_200(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_institute_owner_returns_200(self):
        user = _make_user('owner2_msg', 'wlhtestmails+owner2_msg@gmail.com', Role.INSTITUTE_OWNER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_head_of_institute_returns_200(self):
        user = _make_user('hoi2_msg', 'wlhtestmails+hoi2_msg@gmail.com', Role.HEAD_OF_INSTITUTE)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_student_role_denied(self):
        user = _make_user('student2_msg', 'wlhtestmails+student2_msg@gmail.com', Role.STUDENT)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_teacher_role_denied(self):
        user = _make_user('teacher2_msg', 'wlhtestmails+teacher2_msg@gmail.com', Role.TEACHER)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/messaging', response['Location'])

    def test_uses_correct_template(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'messaging/compose.html')

    def test_extends_base_template(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'base.html')

    def test_school_in_context_when_admin_has_school(self):
        user, school = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.context['school'], school)

    def test_school_none_in_context_when_no_school(self):
        user = _make_user('noschl_msg', 'wlhtestmails+noschl_msg@gmail.com', Role.ADMIN)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['school'])

    def test_page_title_contains_messaging(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'Messaging')

    def test_page_contains_new_message_heading(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'New Message')

    def test_page_shows_email_channel_option(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'Email')

    def test_page_shows_sms_disabled(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'SMS')

    def test_post_method_not_allowed(self):
        user, _ = _make_admin_with_school()
        self.client.force_login(user)
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 405)
