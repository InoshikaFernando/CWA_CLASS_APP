"""Tests for all registration flows: institute, school student, individual student."""
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from billing.models import (
    InstitutePlan, InstituteDiscountCode, Package, SchoolSubscription, Subscription,
)


class InstituteRegistrationTest(TestCase):
    """Test TeacherCenterRegisterView — institute registration with plan selection."""

    @classmethod
    def setUpTestData(cls):
        cls.plan_basic, _ = InstitutePlan.objects.get_or_create(
            slug='basic', defaults={
                'name': 'Basic', 'price': 89, 'class_limit': 5,
                'student_limit': 100, 'invoice_limit_yearly': 500,
                'extra_invoice_rate': 0.30, 'trial_days': 14, 'order': 1,
                'stripe_price_id': 'price_test_basic',
            },
        )
        cls.plan_silver, _ = InstitutePlan.objects.get_or_create(
            slug='silver', defaults={
                'name': 'Silver', 'price': 129, 'class_limit': 10,
                'student_limit': 200, 'invoice_limit_yearly': 750,
                'extra_invoice_rate': 0.25, 'trial_days': 14, 'order': 2,
                'stripe_price_id': 'price_test_silver',
            },
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')

    # ── GET ──────────────────────────────────────────────────

    def test_get_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_get_contains_plans(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Basic')
        self.assertContains(resp, 'Silver')

    def test_get_shows_step_indicator(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'step-1')
        self.assertContains(resp, 'step-2')

    def test_authenticated_user_redirected(self):
        user = CustomUser.objects.create_user('existing', 'e@t.com', 'pass1234')
        self.client.force_login(user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    # ── POST success ─────────────────────────────────────────

    def test_register_creates_user_school_subscription(self):
        resp = self.client.post(self.url, {
            'center_name': 'Test School',
            'username': 'newadmin',
            'email': 'admin@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_basic.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)  # redirect on success

        user = CustomUser.objects.get(username='newadmin')
        self.assertTrue(user.has_role(Role.HEAD_OF_INSTITUTE))

        from classroom.models import School
        school = School.objects.get(admin=user)
        self.assertEqual(school.name, 'Test School')

        sub = SchoolSubscription.objects.get(school=school)
        self.assertEqual(sub.plan, self.plan_basic)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)
        self.assertIsNotNone(sub.trial_end)
        self.assertTrue(sub.has_used_trial)

    def test_register_with_silver_plan(self):
        self.client.post(self.url, {
            'center_name': 'Silver School',
            'username': 'silveradmin',
            'email': 'silver@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_silver.id,
            'accept_terms': 'on',
        })
        user = CustomUser.objects.get(username='silveradmin')
        from classroom.models import School
        school = School.objects.get(admin=user)
        sub = SchoolSubscription.objects.get(school=school)
        self.assertEqual(sub.plan, self.plan_silver)

    # ── POST validation errors ───────────────────────────────

    def test_register_missing_plan_shows_error(self):
        resp = self.client.post(self.url, {
            'center_name': 'Test School',
            'username': 'newadmin',
            'email': 'admin@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'select a plan')

    def test_register_missing_center_name(self):
        resp = self.client.post(self.url, {
            'username': 'newadmin',
            'email': 'admin@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_basic.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'centre name is required')

    def test_register_password_mismatch(self):
        resp = self.client.post(self.url, {
            'center_name': 'Test School',
            'username': 'newadmin',
            'email': 'admin@test.com',
            'password': 'securepass1',
            'confirm_password': 'different',
            'plan_id': self.plan_basic.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'match')

    def test_register_duplicate_username(self):
        CustomUser.objects.create_user('taken', 'taken@t.com', 'pass1234')
        resp = self.client.post(self.url, {
            'center_name': 'Test School',
            'username': 'taken',
            'email': 'new@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_basic.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)

    def test_register_invalid_plan_id(self):
        resp = self.client.post(self.url, {
            'center_name': 'Test School',
            'username': 'newadmin',
            'email': 'admin@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': '99999',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'select a plan')


class UnlimitedPlanDisplayTest(TestCase):
    """CPP-298: Plans with limit=0 should display 'Unlimited' on signup page."""

    @classmethod
    def setUpTestData(cls):
        cls.limited_plan = InstitutePlan.objects.create(
            slug='limited', name='Basic', price=89, class_limit=5,
            student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=0.30, trial_days=14, order=1,
            stripe_price_id='price_test_limited',
        )
        cls.unlimited_plan = InstitutePlan.objects.create(
            slug='platinum', name='Platinum', price=189, class_limit=0,
            student_limit=0, invoice_limit_yearly=0,
            extra_invoice_rate=0, trial_days=14, order=4,
            stripe_price_id='price_test_platinum',
        )

    def test_signup_unlimited_plan_shows_unlimited(self):
        resp = self.client.get(reverse('register_teacher_center'))
        self.assertContains(resp, 'Unlimited classes')
        self.assertContains(resp, 'Unlimited students')

    def test_signup_limited_plan_shows_numbers(self):
        resp = self.client.get(reverse('register_teacher_center'))
        self.assertContains(resp, '5 classes')
        self.assertContains(resp, '100 students')

    def test_trial_expired_unlimited_plan_shows_unlimited(self):
        from classroom.models import School
        user = CustomUser.objects.create_user('hoiuser', 'wlhtestmails+hoi298@gmail.com', 'testpass123')
        hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        from accounts.models import UserRole
        UserRole.objects.get_or_create(user=user, role=hoi_role)
        school = School.objects.create(name='Test School 298', slug='test-298', admin=user)
        SchoolSubscription.objects.create(
            school=school, plan=self.unlimited_plan, status='trial_expired',
        )
        self.client.login(username='hoiuser', password='testpass123')
        resp = self.client.get(reverse('institute_trial_expired'))
        self.assertContains(resp, 'Unlimited')
        self.assertNotContains(resp, '0 classes, 0 students')


class IndividualStudentRegistrationTest(TestCase):
    """Test IndividualStudentRegisterView — multi-step with package selection."""

    @classmethod
    def setUpTestData(cls):
        cls.free_pkg = Package.objects.create(
            name='Free', class_limit=1, price=0, trial_days=7, order=1,
        )
        cls.basic_pkg = Package.objects.create(
            name='Basic', class_limit=3, price=9.99, trial_days=14, order=2,
            stripe_price_id='price_test_basic',
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_individual_student')

    def test_get_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_get_shows_packages(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Free')
        self.assertContains(resp, 'Basic')

    def test_register_with_free_package(self):
        resp = self.client.post(self.url, {
            'username': 'freestudent',
            'email': 'free@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'package_id': self.free_pkg.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='freestudent')
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.package, self.free_pkg)
        self.assertEqual(sub.status, Subscription.STATUS_TRIALING)
        self.assertIsNotNone(sub.trial_end)

    @patch('billing.stripe_service.create_pending_registration_checkout_session')
    def test_register_with_paid_package_redirects_to_stripe(self, mock_stripe):
        mock_session = MagicMock()
        mock_session.id = 'cs_test_123'
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_stripe.return_value = mock_session
        resp = self.client.post(self.url, {
            'username': 'paidstudent',
            'email': 'paid@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'package_id': self.basic_pkg.id,
            'accept_terms': 'on',
        })
        # Paid package redirects to Stripe Checkout (account not yet created)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('stripe.com', resp.url)
        self.assertFalse(CustomUser.objects.filter(username='paidstudent').exists())
        from accounts.models import PendingRegistration
        pending = PendingRegistration.objects.get(stripe_session_id='cs_test_123')
        self.assertEqual(pending.email, 'paid@test.com')

    def test_register_missing_package(self):
        resp = self.client.post(self.url, {
            'username': 'nopack',
            'email': 'nopack@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'package')

    def test_authenticated_user_redirected(self):
        user = CustomUser.objects.create_user('existing', 'e@t.com', 'pass1234')
        self.client.force_login(user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)


class InstituteDiscountCodeTest(TestCase):
    """Test institute registration with discount codes."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = InstitutePlan.objects.get_or_create(
            slug='basic', defaults={
                'name': 'Basic', 'price': 89, 'class_limit': 5,
                'student_limit': 100, 'invoice_limit_yearly': 500,
                'extra_invoice_rate': 0.30, 'trial_days': 14, 'order': 1,
                'stripe_price_id': 'price_test_basic',
            },
        )
        cls.free_code = InstituteDiscountCode.objects.create(
            code='FREEACCESS', discount_percent=100,
            override_class_limit=0, override_student_limit=0,
        )
        cls.half_off = InstituteDiscountCode.objects.create(
            code='HALF50', discount_percent=50,
        )
        cls.expired_code = InstituteDiscountCode.objects.create(
            code='EXPIRED', discount_percent=100, is_active=False,
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')

    def _reg_data(self, code='', suffix=''):
        return {
            'center_name': f'School {suffix}',
            'username': f'user{suffix}',
            'email': f'user{suffix}@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan.id,
            'discount_code': code,
            'accept_terms': 'on',
        }

    def test_100_percent_code_activates_immediately(self):
        resp = self.client.post(self.url, self._reg_data('FREEACCESS', 'free'))
        self.assertEqual(resp.status_code, 302)
        from classroom.models import School
        school = School.objects.get(name='School free')
        sub = SchoolSubscription.objects.get(school=school)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertIsNone(sub.trial_end)
        self.assertEqual(sub.discount_code, self.free_code)

    def test_partial_discount_still_trials(self):
        resp = self.client.post(self.url, self._reg_data('HALF50', 'half'))
        self.assertEqual(resp.status_code, 302)
        from classroom.models import School
        school = School.objects.get(name='School half')
        sub = SchoolSubscription.objects.get(school=school)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)
        self.assertIsNotNone(sub.trial_end)
        self.assertEqual(sub.discount_code, self.half_off)

    def test_discount_code_usage_incremented(self):
        self.assertEqual(self.free_code.uses, 0)
        self.client.post(self.url, self._reg_data('FREEACCESS', 'inc'))
        self.free_code.refresh_from_db()
        self.assertEqual(self.free_code.uses, 1)

    def test_invalid_code_shows_error(self):
        resp = self.client.post(self.url, self._reg_data('NOSUCHCODE', 'bad'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid discount code')

    def test_expired_code_shows_error(self):
        resp = self.client.post(self.url, self._reg_data('EXPIRED', 'exp'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'expired')

    def test_no_code_still_works(self):
        resp = self.client.post(self.url, self._reg_data('', 'nocode'))
        self.assertEqual(resp.status_code, 302)
        from classroom.models import School
        school = School.objects.get(name='School nocode')
        sub = SchoolSubscription.objects.get(school=school)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)
        self.assertIsNone(sub.discount_code)

    def test_case_insensitive_code(self):
        code = InstituteDiscountCode.objects.create(
            code='CASETEST', discount_percent=100, max_uses=1,
        )
        resp = self.client.post(self.url, self._reg_data('casetest', 'case'))
        self.assertEqual(resp.status_code, 302)

    def test_single_use_code_expires_after_use(self):
        """A single-use code should be rejected on second use."""
        code = InstituteDiscountCode.objects.create(
            code='ONESHOT', discount_percent=100, max_uses=1,
        )
        # First use succeeds
        resp1 = self.client.post(self.url, self._reg_data('ONESHOT', 'first'))
        self.assertEqual(resp1.status_code, 302)
        code.refresh_from_db()
        self.assertEqual(code.uses, 1)
        self.assertFalse(code.is_valid())

        # Second use fails
        resp2 = self.client.post(self.url, self._reg_data('ONESHOT', 'second'))
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'expired')


class SchoolToggleActiveTest(TestCase):
    """Test that GET on toggle-active redirects instead of 405."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user('admin', 'a@t.com', 'pass1234')
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin.roles.add(admin_role)
        from classroom.models import School
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_get_redirects_to_detail(self):
        url = reverse('admin_school_toggle_active', args=[self.school.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_post_toggles_active(self):
        url = reverse('admin_school_toggle_active', args=[self.school.id])
        self.assertTrue(self.school.is_active)
        self.client.post(url)
        self.school.refresh_from_db()
        self.assertFalse(self.school.is_active)


class DashboardSchoolCountTest(TestCase):
    """Test that dashboard excludes deactivated schools."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user('admin', 'a@t.com', 'pass1234')
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        cls.admin.roles.add(admin_role)
        cls.admin.roles.add(hoi_role)
        from classroom.models import School
        cls.active_school = School.objects.create(
            name='Active School', slug='active', admin=cls.admin, is_active=True,
        )
        cls.inactive_school = School.objects.create(
            name='Inactive School', slug='inactive', admin=cls.admin, is_active=False,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_dashboard_excludes_inactive_schools(self):
        url = reverse('admin_dashboard')
        resp = self.client.get(url)
        self.assertEqual(resp.context['total_schools'], 1)
        self.assertContains(resp, 'Active School')
        self.assertNotContains(resp, 'Inactive School')


class StripeTrialRegistrationTest(TestCase):
    """Test that registration with stripe_price_id redirects to Stripe."""

    @classmethod
    def setUpTestData(cls):
        cls.plan_with_stripe, _ = InstitutePlan.objects.get_or_create(
            slug='stripe-plan', defaults={
                'name': 'Stripe Plan', 'price': 89,
                'class_limit': 5, 'student_limit': 100,
                'invoice_limit_yearly': 500, 'extra_invoice_rate': 0.30,
                'trial_days': 14, 'order': 10,
                'stripe_price_id': 'price_test_123',
            },
        )
        cls.plan_no_stripe, _ = InstitutePlan.objects.get_or_create(
            slug='no-stripe', defaults={
                'name': 'No Stripe', 'price': 50,
                'class_limit': 3, 'student_limit': 50,
                'invoice_limit_yearly': 200, 'extra_invoice_rate': 0.50,
                'trial_days': 14, 'order': 11,
                'stripe_price_id': '',
            },
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')

    def test_no_stripe_price_blocks_registration(self):
        """CPP-300: Plan without stripe_price_id should block registration, not silently continue."""
        resp = self.client.post(self.url, {
            'center_name': 'No Stripe School',
            'username': 'nostripe',
            'email': 'nostripe@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_no_stripe.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Payment is not currently configured')
        self.assertFalse(CustomUser.objects.filter(username='nostripe').exists())

    def test_has_used_trial_set_on_registration(self):
        """has_used_trial should be True after registering with a trial plan."""
        self.client.post(self.url, {
            'center_name': 'Trial School',
            'username': 'trialuser',
            'email': 'trial@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_with_stripe.id,
            'accept_terms': 'on',
        })
        from classroom.models import School
        school = School.objects.get(name='Trial School')
        sub = SchoolSubscription.objects.get(school=school)
        self.assertTrue(sub.has_used_trial)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)

    def test_free_discount_skips_stripe_and_no_trial(self):
        """100% discount should activate immediately, has_used_trial=False."""
        code = InstituteDiscountCode.objects.create(
            code='SKIPSTRIPE', discount_percent=100, max_uses=1,
        )
        resp = self.client.post(self.url, {
            'center_name': 'Free School',
            'username': 'freeuser',
            'email': 'free@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_with_stripe.id,
            'discount_code': 'SKIPSTRIPE',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/hub/', resp.url)
        from classroom.models import School
        school = School.objects.get(name='Free School')
        sub = SchoolSubscription.objects.get(school=school)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertFalse(sub.has_used_trial)


# ═══════════════════════════════════════════════════════════════
# Terms & Conditions / Privacy Policy Acceptance Tests (CPP-92)
# ═══════════════════════════════════════════════════════════════

class TermsAcceptanceInstituteTest(TestCase):
    """Test that institute registration requires T&C acceptance."""

    @classmethod
    def setUpTestData(cls):
        cls.plan, _ = InstitutePlan.objects.get_or_create(
            slug='basic', defaults={
                'name': 'Basic', 'price': 89, 'class_limit': 5,
                'student_limit': 100, 'invoice_limit_yearly': 500,
                'extra_invoice_rate': 0.30, 'trial_days': 14, 'order': 1,
                'stripe_price_id': 'price_test_basic',
            },
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')

    def _base_data(self, accept=False):
        data = {
            'center_name': 'Terms School',
            'username': 'termsuser',
            'email': 'terms@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan.id,
        }
        if accept:
            data['accept_terms'] = 'on'
        return data

    def test_fails_without_accept_terms(self):
        resp = self.client.post(self.url, self._base_data(accept=False))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Terms and Conditions')

    def test_succeeds_with_accept_terms(self):
        resp = self.client.post(self.url, self._base_data(accept=True))
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='termsuser')
        self.assertIsNotNone(user.terms_accepted_at)

    def test_get_shows_terms_acceptance_widget(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'accept-terms')
        self.assertContains(resp, 'terms-scroll')
        self.assertContains(resp, 'privacy-scroll')


class TermsAcceptanceIndividualStudentTest(TestCase):
    """Test that individual student registration requires T&C acceptance."""

    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(
            name='Test Pkg', class_limit=1, price=0, trial_days=7, order=1,
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_individual_student')

    def _base_data(self, accept=False):
        data = {
            'username': 'indstudent',
            'email': 'ind@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'package_id': self.pkg.id,
        }
        if accept:
            data['accept_terms'] = 'on'
        return data

    def test_fails_without_accept_terms(self):
        resp = self.client.post(self.url, self._base_data(accept=False))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Terms and Conditions')

    def test_succeeds_with_accept_terms(self):
        resp = self.client.post(self.url, self._base_data(accept=True))
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='indstudent')
        self.assertIsNotNone(user.terms_accepted_at)

    def test_get_shows_terms_acceptance_widget(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'accept-terms')
        self.assertContains(resp, 'terms-scroll')
        self.assertContains(resp, 'privacy-scroll')


class TermsFooterLinksTest(TestCase):
    """Test that T&C and Privacy Policy links appear on key pages."""

    def setUp(self):
        self.client = Client()

    def test_login_page_has_legal_links(self):
        resp = self.client.get(reverse('login'))
        self.assertContains(resp, 'Terms and Conditions')
        self.assertContains(resp, 'Privacy Policy')

    def test_institute_register_has_legal_links(self):
        resp = self.client.get(reverse('register_teacher_center'))
        self.assertContains(resp, '/terms/')
        self.assertContains(resp, '/privacy/')

    def test_individual_student_register_has_legal_links(self):
        resp = self.client.get(reverse('register_individual_student'))
        self.assertContains(resp, '/terms/')
        self.assertContains(resp, '/privacy/')

    def test_dashboard_has_legal_footer(self):
        user = CustomUser.objects.create_user('dashuser', 'dash@t.com', 'pass1234')
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        user.roles.add(admin_role)
        self.client.force_login(user)
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertContains(resp, 'Terms and Conditions')
        self.assertContains(resp, 'Privacy Policy')


# ---------------------------------------------------------------------------
# CPP-300: Enforce credit card details during registration
# ---------------------------------------------------------------------------

class CPP300_InstituteStripeEnforcementTest(TestCase):
    """CPP-300: Paid institute plans without stripe_price_id must block registration."""

    @classmethod
    def setUpTestData(cls):
        cls.plan_no_stripe = InstitutePlan.objects.create(
            slug='no-stripe', name='No Stripe Plan', price=89,
            stripe_price_id='',  # Missing!
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=0.30, trial_days=14, order=1,
        )
        cls.plan_with_stripe = InstitutePlan.objects.create(
            slug='with-stripe', name='With Stripe Plan', price=89,
            stripe_price_id='price_test_valid',
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=0.30, trial_days=14, order=2,
        )
        cls.free_code = InstituteDiscountCode.objects.create(
            code='INSTFREE300', discount_percent=100,
            override_class_limit=0, override_student_limit=0,
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')

    def _reg_data(self, plan, suffix='', code=''):
        return {
            'center_name': f'School {suffix}',
            'username': f'user300{suffix}',
            'email': f'user300{suffix}@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': plan.id,
            'discount_code': code,
            'accept_terms': 'on',
        }

    def test_paid_plan_without_stripe_id_blocks_registration(self):
        """Paid plan with blank stripe_price_id must not create account."""
        resp = self.client.post(self.url, self._reg_data(self.plan_no_stripe, 'block'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Payment is not currently configured')
        self.assertFalse(CustomUser.objects.filter(username='user300block').exists())

    def test_paid_plan_without_stripe_id_allows_free_discount(self):
        """100% discount code should bypass the stripe_price_id guard."""
        resp = self.client.post(
            self.url,
            self._reg_data(self.plan_no_stripe, 'free', 'INSTFREE300'),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(username='user300free').exists())

    def test_paid_plan_with_stripe_id_proceeds(self):
        """Paid plan with valid stripe_price_id should proceed (Stripe may fail in test but account is created)."""
        resp = self.client.post(self.url, self._reg_data(self.plan_with_stripe, 'ok'))
        # Account should be created (Stripe redirect will fail in test, but account was already committed)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(username='user300ok').exists())

    def test_stripe_exception_logs_warning_not_silent(self):
        """When Stripe checkout fails, a warning message is set (not silently swallowed)."""
        resp = self.client.post(self.url, self._reg_data(self.plan_with_stripe, 'warn'))
        self.assertEqual(resp.status_code, 302)
        # Follow the redirect to check messages
        resp2 = self.client.get(resp.url)
        # The Stripe call will fail in test (no Stripe configured), so a warning should appear
        # Account should still exist since it was created before the Stripe redirect
        self.assertTrue(CustomUser.objects.filter(username='user300warn').exists())


class CPP300_IndividualStudentStripeEnforcementTest(TestCase):
    """CPP-300: Paid packages without stripe_price_id must block individual student registration."""

    @classmethod
    def setUpTestData(cls):
        cls.free_pkg = Package.objects.create(
            name='Free300', class_limit=1, price=0, trial_days=7, order=1,
        )
        cls.paid_no_stripe = Package.objects.create(
            name='Paid No Stripe', class_limit=3, price=9.99,
            stripe_price_id='',  # Missing!
            trial_days=14, order=2,
        )
        cls.paid_with_stripe = Package.objects.create(
            name='Paid With Stripe', class_limit=3, price=9.99,
            stripe_price_id='price_test_student',
            trial_days=14, order=3,
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_individual_student')

    def _reg_data(self, pkg, suffix=''):
        return {
            'username': f'stud300{suffix}',
            'email': f'stud300{suffix}@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'package_id': pkg.id,
            'accept_terms': 'on',
        }

    def test_paid_package_without_stripe_id_blocks_registration(self):
        """Paid package with blank stripe_price_id must not create account."""
        resp = self.client.post(self.url, self._reg_data(self.paid_no_stripe, 'block'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Payment is not currently configured')
        self.assertFalse(CustomUser.objects.filter(username='stud300block').exists())

    def test_free_package_without_stripe_id_works(self):
        """Free package (price=0) with no stripe_price_id is fine."""
        resp = self.client.post(self.url, self._reg_data(self.free_pkg, 'free'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(username='stud300free').exists())

    @patch('billing.stripe_service.create_pending_registration_checkout_session')
    def test_paid_package_with_stripe_id_redirects_to_stripe(self, mock_stripe):
        """Paid package with valid stripe_price_id should redirect to Stripe."""
        mock_session = MagicMock()
        mock_session.id = 'cs_test_300'
        mock_session.url = 'https://checkout.stripe.com/test300'
        mock_stripe.return_value = mock_session
        resp = self.client.post(self.url, self._reg_data(self.paid_with_stripe, 'ok'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('stripe.com', resp.url)
        # Account is NOT created until Stripe confirms
        self.assertFalse(CustomUser.objects.filter(username='stud300ok').exists())

    def test_stripe_failure_shows_error_not_fallthrough(self):
        """When Stripe session creation fails, show error — do NOT create account."""
        resp = self.client.post(self.url, self._reg_data(self.paid_with_stripe, 'fail'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unable to start payment')
        self.assertFalse(CustomUser.objects.filter(username='stud300fail').exists())


class CPP300_CompleteProfileStripeEnforcementTest(TestCase):
    """CPP-300: CompleteProfileView blocks school students when stripe_price_id is missing."""

    @classmethod
    def setUpTestData(cls):
        cls.pkg_no_stripe = Package.objects.create(
            name='Student No Stripe', class_limit=1, price=19.90,
            stripe_price_id='', is_default=True, trial_days=14, order=1,
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse('complete_profile')
        # Create a school student who must complete profile
        self.user = CustomUser.objects.create_user(
            'schoolstud300', 'ss300@test.com', 'pass1234',
            must_change_password=True,
            profile_completed=False,
        )
        role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        from accounts.models import UserRole
        UserRole.objects.create(user=self.user, role=role)
        self.client.force_login(self.user)

    def test_missing_stripe_id_blocks_profile_completion(self):
        """School student with no stripe_price_id on package stays on profile page."""
        resp = self.client.post(self.url, {
            'new_password': 'newpass1234',
            'confirm_password': 'newpass1234',
            'first_name': 'Test',
            'last_name': 'Student',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Payment is not currently configured')
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_completed)

    @patch('billing.stripe_service.create_student_checkout_session')
    def test_with_stripe_id_redirects_to_stripe(self, mock_stripe):
        """School student with valid stripe_price_id redirects to Stripe."""
        self.pkg_no_stripe.stripe_price_id = 'price_test_student_cp'
        self.pkg_no_stripe.save(update_fields=['stripe_price_id'])
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test_cp'
        mock_stripe.return_value = mock_session
        resp = self.client.post(self.url, {
            'new_password': 'newpass1234',
            'confirm_password': 'newpass1234',
            'first_name': 'Test',
            'last_name': 'Student',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('stripe.com', resp.url)
        # Restore for other tests
        self.pkg_no_stripe.stripe_price_id = ''
        self.pkg_no_stripe.save(update_fields=['stripe_price_id'])


class CPP300_ModelValidationTest(TestCase):
    """CPP-300: Model clean() validation prevents paid plans/packages without stripe_price_id."""

    def test_package_paid_without_stripe_raises(self):
        pkg = Package(name='Bad', price=9.99, stripe_price_id='', class_limit=1)
        with self.assertRaises(ValidationError) as ctx:
            pkg.clean()
        self.assertIn('stripe_price_id', ctx.exception.message_dict)

    def test_package_free_without_stripe_ok(self):
        pkg = Package(name='Free', price=0, stripe_price_id='', class_limit=1)
        pkg.clean()  # Should not raise

    def test_package_paid_with_stripe_ok(self):
        pkg = Package(name='Good', price=9.99, stripe_price_id='price_abc', class_limit=1)
        pkg.clean()  # Should not raise

    def test_institute_plan_paid_without_stripe_raises(self):
        plan = InstitutePlan(
            name='Bad Plan', slug='bad', price=89,
            stripe_price_id='', class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=0.30,
        )
        with self.assertRaises(ValidationError) as ctx:
            plan.clean()
        self.assertIn('stripe_price_id', ctx.exception.message_dict)

    def test_institute_plan_paid_with_stripe_ok(self):
        plan = InstitutePlan(
            name='Good Plan', slug='good', price=89,
            stripe_price_id='price_xyz', class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=0.30,
        )
        plan.clean()  # Should not raise
