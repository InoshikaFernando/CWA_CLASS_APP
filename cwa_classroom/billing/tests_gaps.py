"""
Tests for all gap fixes (A-X) from SPEC_FULL_SYSTEM.md.
Each test class covers one or more gaps.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone
from django.core.cache import cache

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, SchoolSubscription, ModuleSubscription,
    Subscription, Package, DiscountCode, InstituteDiscountCode,
)
from classroom.models import School, ClassRoom, SchoolStudent


def _create_role(name, display_name=None):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_hoi_with_school(username='hoi', plan_status='active'):
    """Create an HoI user with a school, plan, and subscription."""
    user = CustomUser.objects.create_user(username=username, password='testpass123', email=f'{username}@test.com')
    role = _create_role(Role.HEAD_OF_INSTITUTE)
    UserRole.objects.create(user=user, role=role)

    school = School.objects.create(name=f'{username} School', slug=f'{username}-school', admin=user)

    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{username}', price=Decimal('89.00'),
        stripe_price_id='price_test', class_limit=5, student_limit=100,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )

    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status=plan_status,
        invoice_year_start=timezone.localdate(),
    )

    return user, school, plan, sub


# ---------------------------------------------------------------------------
# Gap B: school_student checkout type handled in webhooks
# ---------------------------------------------------------------------------

class GapB_SchoolStudentCheckoutTest(TestCase):
    def test_school_student_checkout_activates_subscription(self):
        """school_student checkout type should activate the student's Subscription."""
        user = CustomUser.objects.create_user(username='student1', password='pass12345', email='s@t.com')
        role = _create_role(Role.STUDENT)
        UserRole.objects.create(user=user, role=role)
        pkg = Package.objects.create(name='Student', price=Decimal('19.90'), stripe_price_id='price_stu')
        sub = Subscription.objects.create(user=user, package=pkg, status=Subscription.STATUS_TRIALING)

        from billing.webhook_handlers import handle_checkout_completed
        event_data = {
            'object': {
                'metadata': {'type': 'school_student', 'user_id': str(user.id), 'package_id': str(pkg.id)},
                'subscription': 'sub_stripe_123',
            }
        }
        handle_checkout_completed(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.stripe_subscription_id, 'sub_stripe_123')


# ---------------------------------------------------------------------------
# Gap D: Discount code override limits applied
# ---------------------------------------------------------------------------

class GapD_DiscountOverrideLimitsTest(TestCase):
    def test_override_class_limit_unlimited(self):
        """A discount code with override_class_limit=0 should grant unlimited classes."""
        user, school, plan, sub = _create_hoi_with_school('hoi_d1')
        discount = InstituteDiscountCode.objects.create(
            code='UNLIMITED_CLASSES', override_class_limit=0, override_student_limit=0,
        )
        sub.discount_code = discount
        sub.save()

        from billing.entitlements import check_class_limit
        allowed, current, limit = check_class_limit(school)
        self.assertTrue(allowed)
        self.assertEqual(limit, 0)  # 0 = unlimited

    def test_override_class_limit_specific(self):
        """A discount code with override_class_limit=50 should use 50 instead of plan's 5."""
        user, school, plan, sub = _create_hoi_with_school('hoi_d2')
        discount = InstituteDiscountCode.objects.create(
            code='MORE_CLASSES', override_class_limit=50,
        )
        sub.discount_code = discount
        sub.save()

        from billing.entitlements import check_class_limit
        allowed, current, limit = check_class_limit(school)
        self.assertTrue(allowed)
        self.assertEqual(limit, 50)

    def test_no_override_uses_plan_limit(self):
        """Without a discount code override, plan limits should apply."""
        user, school, plan, sub = _create_hoi_with_school('hoi_d3')

        from billing.entitlements import check_class_limit
        allowed, current, limit = check_class_limit(school)
        self.assertEqual(limit, 5)  # plan.class_limit


# ---------------------------------------------------------------------------
# Gap C: invoice_year_start and auto-reset
# ---------------------------------------------------------------------------

class GapC_InvoiceYearStartTest(TestCase):
    def test_record_invoice_usage_auto_resets_after_year(self):
        """Invoice counter should reset after 365 days."""
        user, school, plan, sub = _create_hoi_with_school('hoi_c1')
        sub.invoices_used_this_year = 499
        sub.invoice_year_start = timezone.localdate() - timedelta(days=366)
        sub.save()

        from billing.entitlements import record_invoice_usage
        record_invoice_usage(school, 1)

        sub.refresh_from_db()
        self.assertEqual(sub.invoices_used_this_year, 1)  # Reset to 0, then +1
        self.assertEqual(sub.invoice_year_start, timezone.localdate())

    def test_record_invoice_usage_no_reset_within_year(self):
        """Invoice counter should NOT reset within the same year."""
        user, school, plan, sub = _create_hoi_with_school('hoi_c2')
        sub.invoices_used_this_year = 10
        sub.invoice_year_start = timezone.localdate() - timedelta(days=100)
        sub.save()

        from billing.entitlements import record_invoice_usage
        record_invoice_usage(school, 5)

        sub.refresh_from_db()
        self.assertEqual(sub.invoices_used_this_year, 15)

    def test_invoice_year_start_initialized_if_null(self):
        """If invoice_year_start is null, it should be set to today."""
        user, school, plan, sub = _create_hoi_with_school('hoi_c3')
        sub.invoice_year_start = None
        sub.save()

        from billing.entitlements import record_invoice_usage
        record_invoice_usage(school, 1)

        sub.refresh_from_db()
        self.assertEqual(sub.invoice_year_start, timezone.localdate())


# ---------------------------------------------------------------------------
# Gap H: cancel_at_period_end synced for institutes
# ---------------------------------------------------------------------------

class GapH_CancelAtPeriodEndTest(TestCase):
    def test_institute_sync_stores_cancel_at_period_end(self):
        """Webhook should store cancel_at_period_end on SchoolSubscription."""
        user, school, plan, sub = _create_hoi_with_school('hoi_h')
        sub.stripe_subscription_id = 'sub_h_test'
        sub.save()

        from billing.webhook_handlers import _sync_institute_subscription
        _sync_institute_subscription(
            'sub_h_test', 'active', {'school_id': str(school.id)},
            cancel_at_period_end=True,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
        )

        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)

    def test_cancel_at_period_end_cleared_on_cancellation(self):
        """When subscription is cancelled, cancel_at_period_end should be cleared."""
        user, school, plan, sub = _create_hoi_with_school('hoi_h2')
        sub.stripe_subscription_id = 'sub_h2_test'
        sub.cancel_at_period_end = True
        sub.save()

        from billing.webhook_handlers import _sync_institute_subscription
        _sync_institute_subscription(
            'sub_h2_test', 'canceled', {'school_id': str(school.id)},
            cancel_at_period_end=False,
            period_start=None, period_end=None,
        )

        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_CANCELLED)


# ---------------------------------------------------------------------------
# Gap F: DiscountCode.stripe_coupon_id field exists
# ---------------------------------------------------------------------------

class GapF_DiscountCodeStripeCouponTest(TestCase):
    def test_discount_code_has_stripe_coupon_field(self):
        """DiscountCode model should have stripe_coupon_id field."""
        dc = DiscountCode.objects.create(
            code='TEST_COUPON', discount_percent=20, stripe_coupon_id='coupon_abc',
        )
        dc.refresh_from_db()
        self.assertEqual(dc.stripe_coupon_id, 'coupon_abc')


# ---------------------------------------------------------------------------
# Gap G: STATUS_SUSPENDED set when school suspended
# ---------------------------------------------------------------------------

class GapG_SuspendedStatusTest(TestCase):
    def test_suspend_school_sets_subscription_suspended(self):
        """Suspending a school should set subscription status to suspended."""
        user, school, plan, sub = _create_hoi_with_school('hoi_g')
        admin = CustomUser.objects.create_user(username='admin_g', password='pass12345', email='adm@t.com')
        admin_role = _create_role(Role.ADMIN)
        UserRole.objects.create(user=admin, role=admin_role)

        self.client.login(username='admin_g', password='pass12345')
        self.client.post('/admin-dashboard/suspend-school/', {'school_id': school.id, 'reason': 'test'})

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_SUSPENDED)

    def test_unsuspend_school_restores_active(self):
        """Unsuspending should restore subscription to active."""
        user, school, plan, sub = _create_hoi_with_school('hoi_g2')
        sub.status = SchoolSubscription.STATUS_SUSPENDED
        sub.save()

        admin = CustomUser.objects.create_user(username='admin_g2', password='pass12345', email='adm2@t.com')
        admin_role = _create_role(Role.ADMIN)
        UserRole.objects.create(user=admin, role=admin_role)

        self.client.login(username='admin_g2', password='pass12345')
        self.client.post('/admin-dashboard/unsuspend-school/', {'school_id': school.id})

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_ACTIVE)


# ---------------------------------------------------------------------------
# Gap A: Middleware catches cancelled/suspended subscriptions
# ---------------------------------------------------------------------------

class GapA_MiddlewareCancelledTest(TestCase):
    def test_cancelled_subscription_redirected(self):
        """User with cancelled subscription should be redirected."""
        from cwa_classroom.middleware import TrialExpiryMiddleware

        sub = MagicMock()
        sub.STATUS_ACTIVE = 'active'
        sub.STATUS_EXPIRED = 'expired'
        sub.STATUS_CANCELLED = 'cancelled'
        sub.status = 'cancelled'
        sub.trial_end = None

        result = TrialExpiryMiddleware._is_trial_expired(sub)
        self.assertTrue(result)

    def test_cancelled_school_sub_blocked(self):
        """School with cancelled subscription should be blocked."""
        from cwa_classroom.middleware import TrialExpiryMiddleware

        result = TrialExpiryMiddleware._is_school_sub_expired(
            MagicMock(status='cancelled', trial_end=None)
        )
        self.assertTrue(result)

    def test_suspended_school_sub_blocked(self):
        """School with suspended subscription should be blocked."""
        from cwa_classroom.middleware import TrialExpiryMiddleware

        result = TrialExpiryMiddleware._is_school_sub_expired(
            MagicMock(status='suspended', trial_end=None)
        )
        self.assertTrue(result)

    def test_active_school_sub_allowed(self):
        """Active subscription should NOT be blocked."""
        from cwa_classroom.middleware import TrialExpiryMiddleware

        result = TrialExpiryMiddleware._is_school_sub_expired(
            MagicMock(status='active', trial_end=None)
        )
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Gap R: Rate limiting on registration (tested with TESTING=False)
# ---------------------------------------------------------------------------

class GapR_RegistrationRateLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        _create_role(Role.STUDENT)

    def tearDown(self):
        cache.clear()

    @override_settings(TESTING=False)
    def test_registration_rate_limited_after_10_attempts(self):
        """Registration should return 429 after 10 attempts from same IP."""
        for i in range(10):
            self.client.post('/accounts/register/school-student/', {
                'first_name': f'Test{i}', 'last_name': 'User',
                'email': f'test{i}@unique.com', 'password': 'password123',
                'confirm_password': 'password123',
            })

        resp = self.client.post('/accounts/register/school-student/', {
            'first_name': 'Blocked', 'last_name': 'User',
            'email': 'blocked@test.com', 'password': 'password123',
            'confirm_password': 'password123',
        })
        self.assertEqual(resp.status_code, 429)


# ---------------------------------------------------------------------------
# Gap S: Rate limiting on webhook
# ---------------------------------------------------------------------------

class GapS_WebhookRateLimitTest(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(TESTING=False)
    def test_webhook_rate_limited(self):
        """Webhook should return 429 after 100 requests per minute."""
        from billing.rate_limiting import check_rate_limit
        # Exhaust the limit
        for _ in range(100):
            check_rate_limit('webhook:127.0.0.1', max_attempts=100, window_seconds=60)

        resp = self.client.post('/stripe/webhook/', content_type='application/json', data='{}')
        self.assertEqual(resp.status_code, 429)


# ---------------------------------------------------------------------------
# Gap K: has_used_trial checked before checkout
# ---------------------------------------------------------------------------

class GapK_HasUsedTrialTest(TestCase):
    @patch('billing.stripe_service.stripe.checkout.Session.create')
    def test_no_trial_when_has_used_trial(self, mock_create):
        """InstituteCheckoutView should not pass trial_period_days when has_used_trial=True."""
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/test')
        user, school, plan, sub = _create_hoi_with_school('hoi_k')
        sub.has_used_trial = True
        sub.stripe_subscription_id = 'sub_k'
        sub.save()

        self.client.login(username='hoi_k', password='testpass123')
        self.client.post('/billing/institute/checkout/', {'plan': plan.slug})

        if mock_create.called:
            call_kwargs = mock_create.call_args
            sub_data = call_kwargs[1].get('subscription_data', {}) if call_kwargs[1] else {}
            # trial_period_days should NOT be in subscription_data
            self.assertNotIn('trial_period_days', sub_data)


# ---------------------------------------------------------------------------
# Gap T: Audit dashboard accessible to admins
# ---------------------------------------------------------------------------

class GapT_AuditDashboardTest(TestCase):
    def test_admin_can_access_dashboard(self):
        """Admin should be able to access the audit dashboard."""
        admin = CustomUser.objects.create_user(username='audit_admin', password='pass12345', email='aa@t.com')
        role = _create_role(Role.ADMIN)
        UserRole.objects.create(user=admin, role=role)

        self.client.login(username='audit_admin', password='pass12345')
        resp = self.client.get('/audit/dashboard/')
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_cannot_access_dashboard(self):
        """Non-admin should be redirected from audit dashboard."""
        user = CustomUser.objects.create_user(username='regular', password='pass12345', email='r@t.com')
        role = _create_role(Role.TEACHER)
        UserRole.objects.create(user=user, role=role)

        self.client.login(username='regular', password='pass12345')
        resp = self.client.get('/audit/dashboard/')
        self.assertNotEqual(resp.status_code, 200)

    def test_audit_log_list_accessible(self):
        """Audit log list should be accessible to admins."""
        admin = CustomUser.objects.create_user(username='audit_admin2', password='pass12345', email='aa2@t.com')
        role = _create_role(Role.ADMIN)
        UserRole.objects.create(user=admin, role=role)

        self.client.login(username='audit_admin2', password='pass12345')
        resp = self.client.get('/audit/logs/')
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Gap I & O: New URL resolution
# ---------------------------------------------------------------------------

class GapIO_URLResolutionTest(TestCase):
    def test_module_toggle_url_resolves(self):
        from django.urls import reverse
        url = reverse('module_toggle')
        self.assertEqual(url, '/billing/institute/module/toggle/')

    def test_billing_history_url_resolves(self):
        from django.urls import reverse
        url = reverse('billing_history')
        self.assertEqual(url, '/billing/history/')

    def test_audit_dashboard_url_resolves(self):
        from django.urls import reverse
        url = reverse('audit_dashboard')
        self.assertEqual(url, '/audit/dashboard/')

    def test_audit_log_list_url_resolves(self):
        from django.urls import reverse
        url = reverse('audit_log_list')
        self.assertEqual(url, '/audit/logs/')


# ---------------------------------------------------------------------------
# Gap M: Email notifications
# ---------------------------------------------------------------------------

class GapM_PaymentFailedEmailTest(TestCase):
    @patch('billing.email_utils.send_mail')
    def test_payment_failed_sends_email(self, mock_send):
        """Payment failure webhook should trigger email notification."""
        user, school, plan, sub = _create_hoi_with_school('hoi_m')
        sub.stripe_subscription_id = 'sub_m_test'
        sub.save()

        from billing.webhook_handlers import handle_payment_failed
        handle_payment_failed({
            'object': {
                'subscription': 'sub_m_test',
                'customer': 'cus_test',
                'amount_due': 8900,
                'currency': 'nzd',
            }
        })

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        self.assertIn('Payment failed', call_kwargs[1]['subject'] if call_kwargs[1] else call_kwargs[0][0])
