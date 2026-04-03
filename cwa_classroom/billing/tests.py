"""
Tests for the subscription, billing, enforcement & security system (CPP-55).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, RequestFactory, Client
from django.utils import timezone
from django.urls import reverse
from django.contrib.sessions.backends.db import SessionStore

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, SchoolSubscription, ModuleSubscription,
    Package, Subscription, StripeEvent,
)
from billing.entitlements import (
    check_class_limit, check_student_limit, check_invoice_limit,
    has_module, has_module_any_school, get_school_for_user,
    get_all_schools_for_user, any_school_has_active_subscription,
    record_invoice_usage,
)
from billing.rate_limiting import check_rate_limit, reset_rate_limit
from classroom.models import School, SchoolStudent, SchoolTeacher, ClassRoom, Department


def _ensure_plans_exist():
    """Create the 4 standard InstitutePlans if they don't exist (e.g. when migrations are skipped)."""
    PLANS = [
        {'slug': 'basic', 'name': 'Basic', 'price': Decimal('89.00'), 'class_limit': 5,
         'student_limit': 100, 'invoice_limit_yearly': 500, 'extra_invoice_rate': Decimal('0.30'), 'order': 0},
        {'slug': 'silver', 'name': 'Silver', 'price': Decimal('149.00'), 'class_limit': 15,
         'student_limit': 300, 'invoice_limit_yearly': 1500, 'extra_invoice_rate': Decimal('0.25'), 'order': 1},
        {'slug': 'gold', 'name': 'Gold', 'price': Decimal('249.00'), 'class_limit': 50,
         'student_limit': 1000, 'invoice_limit_yearly': 5000, 'extra_invoice_rate': Decimal('0.20'), 'order': 2},
        {'slug': 'platinum', 'name': 'Platinum', 'price': Decimal('449.00'), 'class_limit': 200,
         'student_limit': 5000, 'invoice_limit_yearly': 20000, 'extra_invoice_rate': Decimal('0.15'), 'order': 3},
    ]
    for p in PLANS:
        InstitutePlan.objects.get_or_create(slug=p['slug'], defaults=p)


def _ensure_packages_exist():
    """Create standard Packages if they don't exist."""
    PACKAGES = [
        {'name': 'Student Plan', 'slug': 'student-plan', 'price': Decimal('0.00'), 'order': 0},
    ]
    for p in PACKAGES:
        Package.objects.get_or_create(slug=p['slug'], defaults=p)


class InstitutePlanModelTest(TestCase):
    """Test InstitutePlan seed data and model behavior."""

    def setUp(self):
        _ensure_plans_exist()

    def test_plans_seeded(self):
        """Four plans should exist."""
        plans = InstitutePlan.objects.all()
        self.assertEqual(plans.count(), 4)
        slugs = list(plans.values_list('slug', flat=True))
        self.assertIn('basic', slugs)
        self.assertIn('silver', slugs)
        self.assertIn('gold', slugs)
        self.assertIn('platinum', slugs)

    def test_basic_plan_limits(self):
        plan = InstitutePlan.objects.get(slug='basic')
        self.assertEqual(plan.price, Decimal('89.00'))
        self.assertEqual(plan.class_limit, 5)
        self.assertEqual(plan.student_limit, 100)
        self.assertEqual(plan.invoice_limit_yearly, 500)
        self.assertEqual(plan.extra_invoice_rate, Decimal('0.30'))

    def test_plan_ordering(self):
        plans = list(InstitutePlan.objects.values_list('slug', flat=True))
        self.assertEqual(plans, ['basic', 'silver', 'gold', 'platinum'])


class SchoolSubscriptionTest(TestCase):
    """Test SchoolSubscription model and properties."""

    def setUp(self):
        _ensure_plans_exist()
        self.user = CustomUser.objects.create_user(
            username='testadmin', email='admin@test.com', password='testpass123',
        )
        self.school = School.objects.create(
            name='Test School', slug='test-school', admin=self.user,
        )
        self.plan = InstitutePlan.objects.get(slug='basic')

    def test_create_trialing_subscription(self):
        sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan,
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end=timezone.now() + timedelta(days=14),
        )
        self.assertTrue(sub.is_active_or_trialing)
        self.assertEqual(sub.trial_days_remaining, 14)

    def test_expired_subscription(self):
        sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan,
            status=SchoolSubscription.STATUS_EXPIRED,
            trial_end=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(sub.is_active_or_trialing)
        self.assertEqual(sub.trial_days_remaining, 0)

    def test_active_subscription(self):
        sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan,
            status=SchoolSubscription.STATUS_ACTIVE,
        )
        self.assertTrue(sub.is_active_or_trialing)


class EntitlementsTest(TestCase):
    """Test entitlement checking functions."""

    def setUp(self):
        _ensure_plans_exist()
        self.user = CustomUser.objects.create_user(
            username='hoi', email='hoi@test.com', password='testpass123',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=self.user, role=role)
        self.school = School.objects.create(
            name='Entitlement School', slug='ent-school', admin=self.user,
        )
        self.plan = InstitutePlan.objects.get(slug='basic')
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan,
            status=SchoolSubscription.STATUS_ACTIVE,
        )

    def test_check_class_limit_within(self):
        allowed, current, limit = check_class_limit(self.school)
        self.assertTrue(allowed)
        self.assertEqual(current, 0)
        self.assertEqual(limit, 5)

    def test_check_class_limit_at_limit(self):
        dept = Department.objects.create(
            name='Dept', school=self.school, is_active=True,
        )
        for i in range(5):
            ClassRoom.objects.create(
                name=f'Class {i}', school=self.school,
                department=dept, created_by=self.user,
            )
        allowed, current, limit = check_class_limit(self.school)
        self.assertFalse(allowed)
        self.assertEqual(current, 5)

    def test_check_student_limit_within(self):
        allowed, current, limit = check_student_limit(self.school)
        self.assertTrue(allowed)
        self.assertEqual(limit, 100)

    def test_check_invoice_limit(self):
        within, current, limit, rate = check_invoice_limit(self.school)
        self.assertTrue(within)
        self.assertEqual(limit, 500)
        self.assertEqual(rate, Decimal('0.30'))

    def test_has_module_false(self):
        self.assertFalse(has_module(self.school, 'teachers_attendance'))

    def test_has_module_true(self):
        ModuleSubscription.objects.create(
            school_subscription=self.sub,
            module='teachers_attendance',
            is_active=True,
        )
        self.assertTrue(has_module(self.school, 'teachers_attendance'))

    def test_has_module_inactive(self):
        ModuleSubscription.objects.create(
            school_subscription=self.sub,
            module='teachers_attendance',
            is_active=False,
        )
        self.assertFalse(has_module(self.school, 'teachers_attendance'))

    def test_get_school_for_user_admin(self):
        school = get_school_for_user(self.user)
        self.assertEqual(school, self.school)

    def test_legacy_school_no_limits(self):
        """Schools without a subscription should have no limits enforced."""
        legacy_school = School.objects.create(
            name='Legacy', slug='legacy', admin=self.user,
        )
        allowed, _, _ = check_class_limit(legacy_school)
        self.assertTrue(allowed)

    def test_record_invoice_usage(self):
        record_invoice_usage(self.school, 3)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.invoices_used_this_year, 3)
        record_invoice_usage(self.school, 2)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.invoices_used_this_year, 5)


class MultiSchoolEntitlementsTest(TestCase):
    """Test multi-school student entitlement logic."""

    def setUp(self):
        _ensure_plans_exist()
        self.student = CustomUser.objects.create_user(
            username='multistudent', email='multi@test.com', password='testpass123',
        )
        student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        UserRole.objects.create(user=self.student, role=student_role)

        # School A: has attendance module
        admin_a = CustomUser.objects.create_user(username='admin_a', password='pass123', email='admin_a@test.com')
        self.school_a = School.objects.create(name='School A', slug='school-a', admin=admin_a)
        plan = InstitutePlan.objects.get(slug='basic')
        self.sub_a = SchoolSubscription.objects.create(
            school=self.school_a, plan=plan, status=SchoolSubscription.STATUS_ACTIVE,
        )
        ModuleSubscription.objects.create(
            school_subscription=self.sub_a, module='students_attendance', is_active=True,
        )
        SchoolStudent.objects.create(school=self.school_a, student=self.student)

        # School B: no modules
        admin_b = CustomUser.objects.create_user(username='admin_b', password='pass123', email='admin_b@test.com')
        self.school_b = School.objects.create(name='School B', slug='school-b', admin=admin_b)
        self.sub_b = SchoolSubscription.objects.create(
            school=self.school_b, plan=plan, status=SchoolSubscription.STATUS_ACTIVE,
        )
        SchoolStudent.objects.create(school=self.school_b, student=self.student)

    def test_get_all_schools(self):
        schools = get_all_schools_for_user(self.student)
        self.assertEqual(schools.count(), 2)

    def test_has_module_any_school(self):
        """Student should access attendance because School A has it."""
        self.assertTrue(has_module_any_school(self.student, 'students_attendance'))

    def test_no_module_any_school(self):
        """No school has progress reports."""
        self.assertFalse(has_module_any_school(self.student, 'student_progress_reports'))

    def test_any_school_active_subscription(self):
        self.assertTrue(any_school_has_active_subscription(self.student))

    def test_all_schools_expired(self):
        """Block if ALL schools are expired."""
        self.sub_a.status = SchoolSubscription.STATUS_EXPIRED
        self.sub_a.save()
        self.sub_b.status = SchoolSubscription.STATUS_EXPIRED
        self.sub_b.save()
        self.assertFalse(any_school_has_active_subscription(self.student))

    def test_one_school_expired_one_active(self):
        """Allow if at least one school is active."""
        self.sub_a.status = SchoolSubscription.STATUS_EXPIRED
        self.sub_a.save()
        self.assertTrue(any_school_has_active_subscription(self.student))


class RateLimitingTest(TestCase):
    """Test rate limiting utility."""

    def test_within_limit(self):
        self.assertTrue(check_rate_limit('test:ip1', 3, 60))
        self.assertTrue(check_rate_limit('test:ip1', 3, 60))
        self.assertTrue(check_rate_limit('test:ip1', 3, 60))

    def test_exceeds_limit(self):
        for _ in range(3):
            check_rate_limit('test:ip2', 3, 60)
        self.assertFalse(check_rate_limit('test:ip2', 3, 60))

    def test_reset_clears_limit(self):
        for _ in range(3):
            check_rate_limit('test:ip3', 3, 60)
        self.assertFalse(check_rate_limit('test:ip3', 3, 60))
        reset_rate_limit('test:ip3')
        self.assertTrue(check_rate_limit('test:ip3', 3, 60))

    def test_different_keys_independent(self):
        for _ in range(3):
            check_rate_limit('test:ip4', 3, 60)
        self.assertFalse(check_rate_limit('test:ip4', 3, 60))
        self.assertTrue(check_rate_limit('test:ip5', 3, 60))


class AccountBlockingTest(TestCase):
    """Test account blocking model fields and middleware behavior."""

    def setUp(self):
        _ensure_plans_exist()
        self.user = CustomUser.objects.create_user(
            username='blocktest', email='block@test.com', password='testpass123',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=self.user, role=role)
        self.school = School.objects.create(
            name='Block School', slug='block-school', admin=self.user,
        )
        plan = InstitutePlan.objects.get(slug='basic')
        SchoolSubscription.objects.create(
            school=self.school, plan=plan,
            status=SchoolSubscription.STATUS_ACTIVE,
        )

    def test_block_user(self):
        self.user.is_blocked = True
        self.user.blocked_reason = 'Test block'
        self.user.block_type = 'permanent'
        self.user.blocked_at = timezone.now()
        self.user.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_blocked)

    def test_blocked_user_redirected(self):
        """Blocked users should be redirected to the blocked page."""
        self.user.is_blocked = True
        self.user.block_type = 'permanent'
        self.user.save()
        client = Client()
        client.force_login(self.user)
        response = client.get('/dashboard/', follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('blocked', response.url)

    def test_temporary_block_auto_expires(self):
        """Temporary blocks should auto-expire."""
        self.user.is_blocked = True
        self.user.block_type = 'temporary'
        self.user.block_expires_at = timezone.now() - timedelta(hours=1)
        self.user.save()
        client = Client()
        client.force_login(self.user)
        response = client.get('/dashboard/', follow=False)
        # Should NOT redirect to blocked page because block expired
        self.assertNotIn('blocked', response.url if response.status_code == 302 else '')

    def test_school_suspension(self):
        self.school.is_suspended = True
        self.school.save()
        client = Client()
        client.force_login(self.user)
        response = client.get('/dashboard/', follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('blocked', response.url)


class RegistrationSubscriptionTest(TestCase):
    """Test that institute registration creates a SchoolSubscription."""

    def test_teacher_center_registration_creates_subscription(self):
        client = Client()
        basic_plan = InstitutePlan.objects.get(slug='basic')
        response = client.post(reverse('register_teacher_center'), {
            'username': 'newschool',
            'email': 'new@school.com',
            'password': 'TestPass123!',
            'confirm_password': 'TestPass123!',
            'center_name': 'New Test School',
            'plan_id': basic_plan.id,
            'accept_terms': 'on',
        })
        self.assertEqual(response.status_code, 302)

        school = School.objects.get(name='New Test School')
        self.assertTrue(hasattr(school, 'subscription'))
        sub = school.subscription
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)
        self.assertIsNotNone(sub.trial_end)
        self.assertEqual(sub.plan.slug, 'basic')
        self.assertGreater(sub.trial_days_remaining, 0)


class ModuleGatingViewTest(TestCase):
    """Test that module-gated views redirect when module is not subscribed."""

    def setUp(self):
        _ensure_plans_exist()
        self.user = CustomUser.objects.create_user(
            username='gatetest', email='gate@test.com', password='testpass123',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=self.user, role=role)
        self.school = School.objects.create(
            name='Gate School', slug='gate-school', admin=self.user,
        )
        plan = InstitutePlan.objects.get(slug='basic')
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=plan,
            status=SchoolSubscription.STATUS_ACTIVE,
        )

    def test_attendance_report_blocked_without_module(self):
        client = Client()
        client.force_login(self.user)
        response = client.get('/department/attendance/', follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('module-required', response.url)

    def test_progress_criteria_blocked_without_module(self):
        client = Client()
        client.force_login(self.user)
        response = client.get('/progress/criteria/', follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('module-required', response.url)

    def test_attendance_allowed_with_module(self):
        ModuleSubscription.objects.create(
            school_subscription=self.sub,
            module='students_attendance',
            is_active=True,
        )
        client = Client()
        client.force_login(self.user)
        response = client.get('/department/attendance/')
        self.assertEqual(response.status_code, 200)


class LoginAuditTest(TestCase):
    """Test that login creates audit log entries."""

    def test_successful_login_logged(self):
        from audit.models import AuditLog
        CustomUser.objects.create_user(
            username='audituser', password='testpass123',
        )
        client = Client()
        client.post(reverse('login'), {
            'username': 'audituser',
            'password': 'testpass123',
        })
        self.assertTrue(
            AuditLog.objects.filter(action='login_success').exists()
        )

    def test_failed_login_logged(self):
        from audit.models import AuditLog
        client = Client()
        client.post(reverse('login'), {
            'username': 'nonexistent',
            'password': 'wrongpass',
        })
        self.assertTrue(
            AuditLog.objects.filter(action='login_failed').exists()
        )


class StripeEventIdempotencyTest(TestCase):
    """Test StripeEvent model for webhook idempotency."""

    def test_create_event(self):
        event = StripeEvent.objects.create(
            event_id='evt_test_123',
            event_type='checkout.session.completed',
            payload={'test': True},
        )
        self.assertTrue(
            StripeEvent.objects.filter(event_id='evt_test_123').exists()
        )

    def test_duplicate_event_rejected(self):
        StripeEvent.objects.create(
            event_id='evt_dup', event_type='test',
        )
        with self.assertRaises(Exception):
            StripeEvent.objects.create(
                event_id='evt_dup', event_type='test',
            )


class URLResolutionTest(TestCase):
    """Test that all new URLs resolve correctly."""

    def test_institute_urls(self):
        urls = [
            'institute_plan_select',
            'institute_trial_expired',
            'institute_plan_upgrade',
            'institute_subscription_dashboard',
            'institute_checkout',
            'institute_checkout_success',
            'institute_change_plan',
            'institute_cancel_subscription',
            'stripe_billing_portal',
            'module_required',
            'account_blocked',
        ]
        for name in urls:
            url = reverse(name)
            self.assertTrue(url, f'{name} should resolve')

    def test_admin_action_urls(self):
        urls = [
            'admin_block_user',
            'admin_unblock_user',
            'admin_suspend_school',
            'admin_unsuspend_school',
        ]
        for name in urls:
            url = reverse(name)
            self.assertTrue(url, f'{name} should resolve')
