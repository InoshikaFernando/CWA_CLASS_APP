"""Tests for all registration flows: institute, school student, individual student."""
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
            },
        )
        cls.plan_silver, _ = InstitutePlan.objects.get_or_create(
            slug='silver', defaults={
                'name': 'Silver', 'price': 129, 'class_limit': 10,
                'student_limit': 200, 'invoice_limit_yearly': 750,
                'extra_invoice_rate': 0.25, 'trial_days': 14, 'order': 2,
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

    def test_register_with_silver_plan(self):
        self.client.post(self.url, {
            'center_name': 'Silver School',
            'username': 'silveradmin',
            'email': 'silver@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'plan_id': self.plan_silver.id,
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
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'select a plan')


class SchoolStudentRegistrationTest(TestCase):
    """Test SchoolStudentRegisterView — simple registration, no package."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_school_student')

    def test_get_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_register_creates_user_with_student_role(self):
        resp = self.client.post(self.url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'username': 'johndoe',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
        })
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='johndoe')
        self.assertTrue(user.has_role(Role.STUDENT))

    def test_register_missing_first_name(self):
        resp = self.client.post(self.url, {
            'last_name': 'Doe',
            'email': 'john@test.com',
            'username': 'johndoe',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'First name')

    def test_register_password_too_short(self):
        resp = self.client.post(self.url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'username': 'johndoe',
            'password': 'short',
            'confirm_password': 'short',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'at least 8')

    def test_authenticated_user_redirected(self):
        user = CustomUser.objects.create_user('existing', 'e@t.com', 'pass1234')
        self.client.force_login(user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)


class IndividualStudentRegistrationTest(TestCase):
    """Test IndividualStudentRegisterView — 3-step with package selection."""

    @classmethod
    def setUpTestData(cls):
        cls.free_pkg = Package.objects.create(
            name='Free', class_limit=1, price=0, trial_days=0, order=1,
        )
        cls.basic_pkg = Package.objects.create(
            name='Basic', class_limit=3, price=9.99, trial_days=14, order=2,
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
        })
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='freestudent')
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.package, self.free_pkg)
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)

    def test_register_with_paid_package_starts_trial(self):
        resp = self.client.post(self.url, {
            'username': 'paidstudent',
            'email': 'paid@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
            'package_id': self.basic_pkg.id,
        })
        # Paid package redirects to checkout
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(username='paidstudent')
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.package, self.basic_pkg)
        self.assertEqual(sub.status, Subscription.STATUS_TRIALING)

    def test_register_missing_package(self):
        resp = self.client.post(self.url, {
            'username': 'nopack',
            'email': 'nopack@test.com',
            'password': 'securepass1',
            'confirm_password': 'securepass1',
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
