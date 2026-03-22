"""
Tests for student creation, login, profile completion, and subscription enforcement.
Covers the bug reported in CPP-55: students added by HoI should receive welcome emails,
be forced to change password on first login, and be subject to school subscription checks.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import School, SchoolStudent


def _create_role(name, display_name=None):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='testpass123', **kwargs):
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'{username}@example.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school_with_subscription(admin_user, status='active'):
    """Create a school with an active subscription."""
    school = School.objects.create(
        name='Test School',
        admin=admin_user,
        is_active=True,
    )
    plan = InstitutePlan.objects.filter(slug='basic').first()
    if not plan:
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic', price=89,
            class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=0.30,
        )
    SchoolSubscription.objects.create(
        school=school,
        plan=plan,
        status=status,
        trial_end=timezone.now() + timedelta(days=14),
    )
    return school


# ---------------------------------------------------------------------------
# 1. Student Creation by HoI
# ---------------------------------------------------------------------------

class StudentCreationTest(TestCase):
    """Test HoI creating a student via the admin dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi_user = _create_user('hoi_user', first_name='Head', last_name='Institute')
        _assign_role(cls.hoi_user, Role.HEAD_OF_INSTITUTE)
        cls.school = _setup_school_with_subscription(cls.hoi_user)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.hoi_user)

    def test_create_student_sets_must_change_password(self):
        """New students should have must_change_password=True."""
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@example.com',
            'password': 'temppass123',
        })
        self.assertEqual(resp.status_code, 302)
        student = CustomUser.objects.get(email='john@example.com')
        self.assertTrue(student.must_change_password)
        self.assertFalse(student.profile_completed)

    def test_create_student_assigns_student_role(self):
        """New students should have the STUDENT role."""
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'jane@example.com',
            'password': 'temppass123',
        })
        student = CustomUser.objects.get(email='jane@example.com')
        self.assertTrue(student.has_role(Role.STUDENT))

    def test_create_student_linked_to_school(self):
        """New students should be linked to the school via SchoolStudent."""
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        self.client.post(url, {
            'first_name': 'Bob',
            'last_name': 'Smith',
            'email': 'bob@example.com',
            'password': 'temppass123',
        })
        student = CustomUser.objects.get(email='bob@example.com')
        self.assertTrue(
            SchoolStudent.objects.filter(school=self.school, student=student).exists()
        )

    @patch('classroom.email_utils.send_staff_welcome_email')
    def test_create_student_sends_welcome_email(self, mock_email):
        """Welcome email should be sent when HoI creates a student."""
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        self.client.post(url, {
            'first_name': 'Alice',
            'last_name': 'Wonder',
            'email': 'alice@example.com',
            'password': 'temppass123',
        })
        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args
        self.assertEqual(call_kwargs.kwargs['role_display'], 'Student')
        self.assertEqual(call_kwargs.kwargs['plain_password'], 'temppass123')


# ---------------------------------------------------------------------------
# 2. Profile Completion on First Login
# ---------------------------------------------------------------------------

class ProfileCompletionTest(TestCase):
    """Test that new students are forced to complete their profile."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi_user = _create_user('hoi_pc', first_name='Head', last_name='PC')
        _assign_role(cls.hoi_user, Role.HEAD_OF_INSTITUTE)
        cls.school = _setup_school_with_subscription(cls.hoi_user)

    def _create_new_student(self):
        """Helper to create a student as HoI would."""
        student = _create_user(
            'new_student', password='temppass123',
            first_name='New', last_name='Student',
        )
        student.must_change_password = True
        student.profile_completed = False
        student.save(update_fields=['must_change_password', 'profile_completed'])
        _assign_role(student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student)
        return student

    def test_new_student_redirected_to_complete_profile(self):
        """Students with must_change_password=True should be redirected."""
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('complete-profile', resp.url)

    def test_complete_profile_page_renders(self):
        """The complete profile page should render for new students."""
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('complete_profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Complete Your Profile')

    def test_complete_profile_changes_password(self):
        """Submitting the form should update the password."""
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        resp = client.post(reverse('complete_profile'), {
            'new_password': 'newpass12345',
            'confirm_password': 'newpass12345',
            'first_name': 'Updated',
            'last_name': 'Student',
            'country': 'New Zealand',
            'region': 'Auckland',
        })
        self.assertEqual(resp.status_code, 302)
        student.refresh_from_db()
        self.assertFalse(student.must_change_password)
        self.assertTrue(student.profile_completed)
        self.assertTrue(student.check_password('newpass12345'))
        self.assertEqual(student.country, 'New Zealand')

    def test_complete_profile_password_mismatch(self):
        """Mismatched passwords should show error."""
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        resp = client.post(reverse('complete_profile'), {
            'new_password': 'newpass12345',
            'confirm_password': 'wrongpass',
            'first_name': 'Updated',
            'last_name': 'Student',
        })
        self.assertEqual(resp.status_code, 200)  # Re-renders form
        student.refresh_from_db()
        self.assertTrue(student.must_change_password)  # Still required

    def test_completed_student_not_redirected(self):
        """Students who already completed their profile should not be redirected."""
        student = _create_user(
            'completed_student', password='goodpass123',
            first_name='Done', last_name='Student',
        )
        _assign_role(student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student)
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('subjects_hub'))
        # Should NOT redirect to complete-profile
        self.assertNotEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# 3. Subscription Enforcement for School Students
# ---------------------------------------------------------------------------

class StudentSubscriptionEnforcementTest(TestCase):
    """Test that school students are subject to subscription checks."""

    def _setup_expired_school(self):
        hoi = _create_user('hoi_exp', first_name='Head', last_name='Expired')
        _assign_role(hoi, Role.HEAD_OF_INSTITUTE)
        school = School.objects.create(name='Expired School', admin=hoi, is_active=True)
        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
            )
        SchoolSubscription.objects.create(
            school=school,
            plan=plan,
            status='trialing',
            trial_end=timezone.now() - timedelta(days=1),  # expired
        )
        return school

    def test_student_blocked_when_school_subscription_expired(self):
        """Students should be blocked when their school subscription has expired."""
        school = self._setup_expired_school()
        student = _create_user('blocked_student', password='pass12345')
        _assign_role(student, Role.STUDENT)
        SchoolStudent.objects.create(school=school, student=student)

        client = Client()
        client.force_login(student)
        resp = client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('trial-expired', resp.url)

    def test_student_allowed_when_school_subscription_active(self):
        """Students should access the app when school subscription is active."""
        hoi = _create_user('hoi_active', first_name='Head', last_name='Active')
        _assign_role(hoi, Role.HEAD_OF_INSTITUTE)
        school = _setup_school_with_subscription(hoi, status='active')
        student = _create_user('active_student', password='pass12345')
        _assign_role(student, Role.STUDENT)
        SchoolStudent.objects.create(school=school, student=student)

        client = Client()
        client.force_login(student)
        resp = client.get(reverse('subjects_hub'))
        # Should not redirect to trial-expired
        if resp.status_code == 302:
            self.assertNotIn('trial-expired', resp.url)


# ---------------------------------------------------------------------------
# 4. Middleware includes STUDENT role
# ---------------------------------------------------------------------------

class MiddlewareStudentRoleTest(TestCase):
    """Test that TrialExpiryMiddleware treats STUDENT as an institute user."""

    def test_student_is_institute_user(self):
        """The _is_institute_user check should include STUDENT role."""
        from cwa_classroom.middleware import TrialExpiryMiddleware
        student = _create_user('middleware_student')
        _assign_role(student, Role.STUDENT)
        self.assertTrue(TrialExpiryMiddleware._is_institute_user(student))

    def test_individual_student_is_not_institute_user(self):
        """INDIVIDUAL_STUDENT should NOT be treated as institute user."""
        from cwa_classroom.middleware import TrialExpiryMiddleware
        student = _create_user('individual_student')
        _assign_role(student, Role.INDIVIDUAL_STUDENT)
        self.assertFalse(TrialExpiryMiddleware._is_institute_user(student))


# ---------------------------------------------------------------------------
# 5. Email or Username Login
# ---------------------------------------------------------------------------

class EmailLoginTest(TestCase):
    """Test that users can login with either username or email."""

    @classmethod
    def setUpTestData(cls):
        cls.user = _create_user(
            'logintest', password='testpass123',
            email='logintest@example.com',
            first_name='Login', last_name='Test',
        )

    def test_login_with_username(self):
        """Should be able to login with username."""
        client = Client()
        resp = client.post(reverse('login'), {
            'username': 'logintest',
            'password': 'testpass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('login', resp.url)

    def test_login_with_email(self):
        """Should be able to login with email address."""
        client = Client()
        resp = client.post(reverse('login'), {
            'username': 'logintest@example.com',
            'password': 'testpass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('login', resp.url)

    def test_login_with_wrong_password(self):
        """Wrong password should fail."""
        client = Client()
        resp = client.post(reverse('login'), {
            'username': 'logintest@example.com',
            'password': 'wrongpassword',
        })
        self.assertEqual(resp.status_code, 200)  # Re-renders login page

    def test_login_with_nonexistent_email(self):
        """Non-existent email should fail gracefully."""
        client = Client()
        resp = client.post(reverse('login'), {
            'username': 'nobody@example.com',
            'password': 'testpass123',
        })
        self.assertEqual(resp.status_code, 200)  # Re-renders login page
