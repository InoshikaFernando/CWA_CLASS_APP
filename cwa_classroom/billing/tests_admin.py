"""
Tests for the Super Admin Billing Management Panel.

Covers access control, plan CRUD + validation, discount code CRUD + validation,
module edit, subscription override, and Stripe sync (mocked).
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, InstituteDiscountCode, ModuleProduct,
    SchoolSubscription, PromoCode, DiscountCode, Package, Subscription,
    ModuleSubscription,
)
from classroom.models import School, SchoolStudent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_superuser(username='super', password='testpass123'):
    return CustomUser.objects.create_superuser(
        username=username, password=password, email=f'{username}@test.com',
    )


def _create_normal_user(username='normal', password='testpass123'):
    return CustomUser.objects.create_user(
        username=username, password=password, email=f'{username}@test.com',
    )


def _create_plan(**kwargs):
    defaults = dict(
        name='Starter', slug='starter', price=Decimal('49.00'),
        class_limit=10, student_limit=100, invoice_limit_yearly=200,
        extra_invoice_rate=Decimal('0.50'),
    )
    defaults.update(kwargs)
    return InstitutePlan.objects.create(**defaults)


def _create_school(admin, name='Test School', slug='test-school'):
    return School.objects.create(name=name, slug=slug, admin=admin)


# ===========================================================================
# Access Control
# ===========================================================================

class AccessControlTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.normaluser = _create_normal_user()

    def test_superuser_can_access_dashboard(self):
        self.client.login(username='super', password='testpass123')
        resp = self.client.get(reverse('billing_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_normal_user_redirected_from_dashboard(self):
        self.client.login(username='normal', password='testpass123')
        resp = self.client.get(reverse('billing_admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_anonymous_user_redirected(self):
        resp = self.client.get(reverse('billing_admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_normal_user_redirected_from_plan_list(self):
        self.client.login(username='normal', password='testpass123')
        resp = self.client.get(reverse('billing_admin_plan_list'))
        self.assertEqual(resp.status_code, 302)

    def test_superuser_can_access_plan_list(self):
        self.client.login(username='super', password='testpass123')
        resp = self.client.get(reverse('billing_admin_plan_list'))
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# Plan CRUD
# ===========================================================================

class PlanCRUDTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    def test_create_plan_success(self):
        resp = self.client.post(reverse('billing_admin_plan_create'), {
            'name': 'Enterprise',
            'price': '199.00',
            'class_limit': '50',
            'student_limit': '500',
            'invoice_limit_yearly': '1000',
            'extra_invoice_rate': '0.25',
            'trial_days': '30',
            'order': '1',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(InstitutePlan.objects.filter(name='Enterprise').exists())
        plan = InstitutePlan.objects.get(name='Enterprise')
        self.assertEqual(plan.slug, 'enterprise')
        self.assertEqual(plan.price, Decimal('199.00'))

    def test_create_plan_auto_slug_dedup(self):
        _create_plan(name='Pro', slug='pro')
        resp = self.client.post(reverse('billing_admin_plan_create'), {
            'name': 'Pro',
            'price': '99.00',
            'class_limit': '10',
            'student_limit': '100',
            'invoice_limit_yearly': '200',
            'extra_invoice_rate': '0.50',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(InstitutePlan.objects.filter(slug='pro-2').exists())

    def test_create_plan_validation_errors(self):
        resp = self.client.post(reverse('billing_admin_plan_create'), {
            'name': '',
            'price': '-5',
            'class_limit': '10',
            'student_limit': '100',
            'invoice_limit_yearly': '200',
            'extra_invoice_rate': '0.50',
        })
        self.assertEqual(resp.status_code, 200)  # Re-renders form
        self.assertContains(resp, 'Name is required')

    def test_create_plan_invalid_price(self):
        resp = self.client.post(reverse('billing_admin_plan_create'), {
            'name': 'Test',
            'price': 'abc',
            'class_limit': '10',
            'student_limit': '100',
            'invoice_limit_yearly': '200',
            'extra_invoice_rate': '0.50',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enter a valid price')

    def test_edit_plan_success(self):
        plan = _create_plan()
        resp = self.client.post(reverse('billing_admin_plan_edit', args=[plan.pk]), {
            'name': 'Starter Plus',
            'price': '59.00',
            'class_limit': '20',
            'student_limit': '200',
            'invoice_limit_yearly': '300',
            'extra_invoice_rate': '0.40',
            'trial_days': '14',
            'order': '0',
        })
        self.assertEqual(resp.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'Starter Plus')
        self.assertEqual(plan.price, Decimal('59.00'))

    def test_edit_plan_get(self):
        plan = _create_plan()
        resp = self.client.get(reverse('billing_admin_plan_edit', args=[plan.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_toggle_activate_plan(self):
        plan = _create_plan(is_active=False)
        resp = self.client.post(reverse('billing_admin_plan_toggle', args=[plan.pk]))
        self.assertEqual(resp.status_code, 302)
        plan.refresh_from_db()
        self.assertTrue(plan.is_active)

    def test_toggle_deactivate_blocked_with_active_subscriptions(self):
        plan = _create_plan()
        school = _create_school(self.superuser)
        SchoolSubscription.objects.create(school=school, plan=plan, status='active')

        resp = self.client.post(reverse('billing_admin_plan_toggle', args=[plan.pk]))
        self.assertEqual(resp.status_code, 302)
        plan.refresh_from_db()
        self.assertTrue(plan.is_active)  # Should NOT have been deactivated

    def test_toggle_deactivate_allowed_no_subscriptions(self):
        plan = _create_plan()
        resp = self.client.post(reverse('billing_admin_plan_toggle', args=[plan.pk]))
        self.assertEqual(resp.status_code, 302)
        plan.refresh_from_db()
        self.assertFalse(plan.is_active)


# ===========================================================================
# Discount Code CRUD
# ===========================================================================

class DiscountCodeCRUDTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    def test_create_discount_code_100_percent(self):
        resp = self.client.post(reverse('billing_admin_discount_create'), {
            'code': 'free school',
            'description': 'Test discount',
            'discount_percent': '100',
            'max_uses': '5',
        })
        self.assertEqual(resp.status_code, 302)
        dc = InstituteDiscountCode.objects.get(code='FREESCHOOL')
        self.assertEqual(dc.discount_percent, 100)
        self.assertTrue(dc.is_fully_free)

    def test_create_discount_duplicate_code(self):
        InstituteDiscountCode.objects.create(code='DUPE', discount_percent=50)
        resp = self.client.post(reverse('billing_admin_discount_create'), {
            'code': 'DUPE',
            'discount_percent': '50',
            'max_uses': '1',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_create_discount_validation(self):
        resp = self.client.post(reverse('billing_admin_discount_create'), {
            'code': '',
            'discount_percent': '150',
            'max_uses': '1',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Code is required')

    def test_edit_discount_code(self):
        dc = InstituteDiscountCode.objects.create(
            code='EDIT50', discount_percent=50, max_uses=10,
        )
        resp = self.client.post(reverse('billing_admin_discount_edit', args=[dc.pk]), {
            'description': 'Updated description',
            'max_uses': '20',
        })
        self.assertEqual(resp.status_code, 302)
        dc.refresh_from_db()
        self.assertEqual(dc.description, 'Updated description')
        self.assertEqual(dc.max_uses, 20)

    def test_edit_discount_get(self):
        dc = InstituteDiscountCode.objects.create(code='VIEW', discount_percent=100)
        resp = self.client.get(reverse('billing_admin_discount_edit', args=[dc.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_toggle_discount_code(self):
        dc = InstituteDiscountCode.objects.create(code='TOGGLE', discount_percent=100)
        self.assertTrue(dc.is_active)

        resp = self.client.post(reverse('billing_admin_discount_toggle', args=[dc.pk]))
        self.assertEqual(resp.status_code, 302)
        dc.refresh_from_db()
        self.assertFalse(dc.is_active)

    def test_discount_list_view(self):
        InstituteDiscountCode.objects.create(code='LIST1', discount_percent=50)
        resp = self.client.get(reverse('billing_admin_discount_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'LIST1')


# ===========================================================================
# Module Edit
# ===========================================================================

class ModuleEditTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')
        self.module, _ = ModuleProduct.objects.get_or_create(
            module='teachers_attendance',
            defaults={'name': 'Teachers Attendance', 'price': Decimal('10.00')},
        )

    def test_module_list(self):
        resp = self.client.get(reverse('billing_admin_module_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Teachers Attendance')

    def test_module_edit_get(self):
        resp = self.client.get(reverse('billing_admin_module_edit', args=[self.module.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_module_edit_post(self):
        resp = self.client.post(reverse('billing_admin_module_edit', args=[self.module.pk]), {
            'name': 'Teacher Attendance Pro',
            'price': '15.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.module.refresh_from_db()
        self.assertEqual(self.module.name, 'Teacher Attendance Pro')
        self.assertEqual(self.module.price, Decimal('15.00'))

    def test_module_edit_validation(self):
        resp = self.client.post(reverse('billing_admin_module_edit', args=[self.module.pk]), {
            'name': '',
            'price': '10.00',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Name is required')

    def test_module_toggle_active(self):
        resp = self.client.post(reverse('billing_admin_module_toggle', args=[self.module.pk]))
        self.assertEqual(resp.status_code, 302)
        self.module.refresh_from_db()
        self.assertFalse(self.module.is_active)


# ===========================================================================
# Subscription Override
# ===========================================================================

class SubscriptionOverrideTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')
        self.school = _create_school(self.superuser)
        self.plan = _create_plan()
        self.plan2 = _create_plan(name='Pro', slug='pro', price=Decimal('99.00'))
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan, status='active',
        )

    def test_subscription_list(self):
        resp = self.client.get(reverse('billing_admin_subscription_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test School')

    def test_subscription_detail(self):
        resp = self.client.get(reverse('billing_admin_subscription_detail', args=[self.sub.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_override_change_plan(self):
        resp = self.client.post(
            reverse('billing_admin_subscription_override', args=[self.sub.pk]),
            {'action': 'change_plan', 'plan_id': self.plan2.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.plan, self.plan2)

    def test_override_extend_trial(self):
        resp = self.client.post(
            reverse('billing_admin_subscription_override', args=[self.sub.pk]),
            {'action': 'extend_trial', 'days': '30'},
        )
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'trialing')
        self.assertIsNotNone(self.sub.trial_end)

    def test_override_reset_invoices(self):
        self.sub.invoices_used_this_year = 50
        self.sub.save()

        resp = self.client.post(
            reverse('billing_admin_subscription_override', args=[self.sub.pk]),
            {'action': 'reset_invoices'},
        )
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.invoices_used_this_year, 0)

    def test_override_change_status(self):
        resp = self.client.post(
            reverse('billing_admin_subscription_override', args=[self.sub.pk]),
            {'action': 'change_status', 'status': 'suspended'},
        )
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'suspended')


# ===========================================================================
# Stripe Sync (mocked)
# ===========================================================================

class StripeSyncTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    @patch('billing.views_admin.PlanSyncStripeView')
    def test_plan_sync_stripe_success(self, _mock):
        """Test plan sync endpoint calls stripe_service."""
        plan = _create_plan()
        with patch('billing.stripe_service.sync_plan_to_stripe') as mock_sync:
            mock_sync.return_value = 'price_new_123'
            resp = self.client.post(reverse('billing_admin_plan_sync', args=[plan.pk]))
            self.assertEqual(resp.status_code, 302)
            mock_sync.assert_called_once_with(plan)

    @patch('billing.stripe_service.sync_plan_to_stripe')
    def test_plan_sync_stripe_failure(self, mock_sync):
        plan = _create_plan()
        mock_sync.side_effect = Exception('Stripe API error')
        resp = self.client.post(reverse('billing_admin_plan_sync', args=[plan.pk]))
        self.assertEqual(resp.status_code, 302)

    @patch('billing.stripe_service.sync_module_to_stripe')
    def test_module_sync_stripe(self, mock_sync):
        module = ModuleProduct.objects.create(
            module='test_mod', name='Test Module', price=Decimal('10.00'),
        )
        mock_sync.return_value = 'price_mod_123'
        resp = self.client.post(reverse('billing_admin_module_sync', args=[module.pk]))
        self.assertEqual(resp.status_code, 302)
        mock_sync.assert_called_once_with(module)


# ===========================================================================
# Stripe Service Unit Tests
# ===========================================================================

class StripeServiceSyncTests(TestCase):
    @patch('billing.stripe_service._stripe_configured', return_value=False)
    def test_sync_plan_raises_when_not_configured(self, _mock):
        from billing.stripe_service import sync_plan_to_stripe
        plan = _create_plan()
        with self.assertRaises(ValueError):
            sync_plan_to_stripe(plan)

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Price.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Product.modify')
    @patch('stripe.Product.retrieve')
    def test_sync_plan_creates_price(self, mock_retrieve, mock_prod_modify, mock_price_create, mock_price_modify, _cfg):
        from billing.stripe_service import sync_plan_to_stripe
        plan = _create_plan()

        mock_retrieve.return_value = MagicMock(id=f'institute_plan_{plan.slug}')
        mock_price_create.return_value = MagicMock(id='price_new_abc')

        result = sync_plan_to_stripe(plan)
        self.assertEqual(result, 'price_new_abc')
        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_new_abc')

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Price.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Product.modify')
    @patch('stripe.Product.retrieve')
    def test_sync_module_creates_price(self, mock_retrieve, mock_prod_modify, mock_price_create, mock_price_modify, _cfg):
        from billing.stripe_service import sync_module_to_stripe
        module = ModuleProduct.objects.create(
            module='test_sync', name='Test Sync', price=Decimal('10.00'),
        )

        mock_retrieve.return_value = MagicMock(id=f'module_{module.module}')
        mock_price_create.return_value = MagicMock(id='price_mod_xyz')

        result = sync_module_to_stripe(module)
        self.assertEqual(result, 'price_mod_xyz')
        module.refresh_from_db()
        self.assertEqual(module.stripe_price_id, 'price_mod_xyz')

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Coupon.create')
    def test_sync_discount_creates_coupon(self, mock_coupon_create, _cfg):
        from billing.stripe_service import sync_discount_to_stripe
        dc = InstituteDiscountCode.objects.create(
            code='HALF', discount_percent=50, max_uses=10,
        )
        mock_coupon_create.return_value = MagicMock(id='coupon_half')

        result = sync_discount_to_stripe(dc)
        self.assertEqual(result, 'coupon_half')
        dc.refresh_from_db()
        self.assertEqual(dc.stripe_coupon_id, 'coupon_half')

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    def test_sync_discount_skips_100_percent(self, _cfg):
        from billing.stripe_service import sync_discount_to_stripe
        dc = InstituteDiscountCode.objects.create(
            code='FREE', discount_percent=100,
        )
        result = sync_discount_to_stripe(dc)
        self.assertEqual(result, '')


# ===========================================================================
# Promo Code CRUD
# ===========================================================================

class PromoCodeCRUDTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    def test_promo_list(self):
        PromoCode.objects.create(code='TEST1', class_limit=5)
        resp = self.client.get(reverse('billing_admin_promo_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'TEST1')

    def test_create_promo(self):
        resp = self.client.post(reverse('billing_admin_promo_create'), {
            'code': 'new promo',
            'description': 'Test promo',
            'class_limit': '3',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PromoCode.objects.filter(code='NEWPROMO').exists())

    def test_create_promo_duplicate(self):
        PromoCode.objects.create(code='DUPE', class_limit=1)
        resp = self.client.post(reverse('billing_admin_promo_create'), {
            'code': 'DUPE',
            'class_limit': '1',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_edit_promo(self):
        promo = PromoCode.objects.create(code='EDITME', class_limit=5)
        resp = self.client.post(reverse('billing_admin_promo_edit', args=[promo.pk]), {
            'description': 'Updated',
            'class_limit': '10',
        })
        self.assertEqual(resp.status_code, 302)
        promo.refresh_from_db()
        self.assertEqual(promo.class_limit, 10)

    def test_toggle_promo(self):
        promo = PromoCode.objects.create(code='TOGGLER', class_limit=1)
        resp = self.client.post(reverse('billing_admin_promo_toggle', args=[promo.pk]))
        self.assertEqual(resp.status_code, 302)
        promo.refresh_from_db()
        self.assertFalse(promo.is_active)


# ===========================================================================
# Dashboard
# ===========================================================================

class DashboardTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    def test_dashboard_renders(self):
        resp = self.client.get(reverse('billing_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Billing Administration')

    def test_dashboard_shows_stats(self):
        _create_plan()
        resp = self.client.get(reverse('billing_admin_dashboard'))
        self.assertContains(resp, '1')  # total_plans count


# ===========================================================================
# Unified Coupon Code Views
# ===========================================================================

class CouponCodeListTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    def test_coupon_list_shows_all_types(self):
        InstituteDiscountCode.objects.create(code='INST1', discount_percent=50)
        PromoCode.objects.create(code='PROMO1', class_limit=5)
        DiscountCode.objects.create(code='DISC1', discount_percent=100)
        resp = self.client.get(reverse('billing_admin_coupon_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'INST1')
        self.assertContains(resp, 'PROMO1')
        self.assertContains(resp, 'DISC1')

    def test_coupon_list_shows_type_badges(self):
        InstituteDiscountCode.objects.create(code='INST2', discount_percent=50)
        PromoCode.objects.create(code='PROMO2', class_limit=5)
        resp = self.client.get(reverse('billing_admin_coupon_list'))
        self.assertContains(resp, 'Institute')
        self.assertContains(resp, 'Student Promo')

    def test_coupon_list_empty(self):
        resp = self.client.get(reverse('billing_admin_coupon_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Coupon Codes')

    def test_coupon_list_requires_superuser(self):
        self.client.logout()
        normal = _create_normal_user()
        self.client.login(username='normal', password='testpass123')
        resp = self.client.get(reverse('billing_admin_coupon_list'))
        self.assertNotEqual(resp.status_code, 200)


class CouponCodeCreateTests(TestCase):
    def setUp(self):
        self.superuser = _create_superuser()
        self.client.login(username='super', password='testpass123')

    def test_create_form_renders(self):
        resp = self.client.get(reverse('billing_admin_coupon_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Create Coupon Code')

    def test_create_institute_code(self):
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'institute',
            'code': 'NEWINST',
            'discount_percent': '50',
            'max_uses': '10',
            'duration': 'forever',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(InstituteDiscountCode.objects.filter(code='NEWINST').exists())
        dc = InstituteDiscountCode.objects.get(code='NEWINST')
        self.assertEqual(dc.discount_percent, 50)
        self.assertEqual(dc.duration, 'forever')

    def test_create_student_promo_code(self):
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'student_promo',
            'code': 'NEWPROMO',
            'discount_percent': '100',
            'grant_days': '30',
            'class_limit': '5',
            'duration': 'forever',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PromoCode.objects.filter(code='NEWPROMO').exists())
        promo = PromoCode.objects.get(code='NEWPROMO')
        self.assertEqual(promo.grant_days, 30)
        self.assertEqual(promo.class_limit, 5)

    def test_create_student_discount_code(self):
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'student_discount',
            'code': 'NEWDISC',
            'discount_percent': '100',
            'duration': 'forever',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(DiscountCode.objects.filter(code='NEWDISC').exists())

    def test_create_with_duration_repeating(self):
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'institute',
            'code': 'REPEAT12',
            'discount_percent': '50',
            'duration': 'repeating',
            'duration_in_months': '12',
        })
        self.assertEqual(resp.status_code, 302)
        dc = InstituteDiscountCode.objects.get(code='REPEAT12')
        self.assertEqual(dc.duration, 'repeating')
        self.assertEqual(dc.duration_in_months, 12)

    def test_create_repeating_without_months_shows_error(self):
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'institute',
            'code': 'NOMONTHS',
            'discount_percent': '50',
            'duration': 'repeating',
            'duration_in_months': '',
        })
        self.assertEqual(resp.status_code, 200)  # re-renders form
        self.assertContains(resp, 'Number of months is required')

    def test_create_with_product_selection(self):
        plan = _create_plan()
        module = ModuleProduct.objects.create(module='test_mod', name='Test Module', price=Decimal('10.00'))
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'institute',
            'code': 'WITHPROD',
            'discount_percent': '50',
            'duration': 'forever',
            'applicable_plans': [str(plan.pk)],
            'applicable_modules': [str(module.pk)],
        })
        self.assertEqual(resp.status_code, 302)
        dc = InstituteDiscountCode.objects.get(code='WITHPROD')
        self.assertEqual(list(dc.applicable_plans.values_list('id', flat=True)), [plan.pk])
        self.assertEqual(list(dc.applicable_modules.values_list('id', flat=True)), [module.pk])

    def test_cross_model_code_uniqueness(self):
        InstituteDiscountCode.objects.create(code='TAKEN', discount_percent=50)
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'student_promo',
            'code': 'TAKEN',
            'discount_percent': '100',
            'duration': 'forever',
        })
        self.assertEqual(resp.status_code, 200)  # re-renders form
        self.assertContains(resp, 'already exists')

    def test_cross_model_uniqueness_promo_to_discount(self):
        PromoCode.objects.create(code='TAKEN2', class_limit=5)
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'student_discount',
            'code': 'TAKEN2',
            'discount_percent': '100',
            'duration': 'forever',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_create_with_duration_once(self):
        resp = self.client.post(reverse('billing_admin_coupon_create'), {
            'target_type': 'student_promo',
            'code': 'ONCEONLY',
            'discount_percent': '25',
            'duration': 'once',
        })
        self.assertEqual(resp.status_code, 302)
        promo = PromoCode.objects.get(code='ONCEONLY')
        self.assertEqual(promo.duration, 'once')


class CouponStripeDurationTests(TestCase):
    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Coupon.create')
    def test_sync_discount_duration_forever(self, mock_coupon, _cfg):
        from billing.stripe_service import sync_discount_to_stripe
        dc = InstituteDiscountCode.objects.create(
            code='FOREVER50', discount_percent=50, duration='forever',
        )
        mock_coupon.return_value = MagicMock(id='coupon_forever')
        sync_discount_to_stripe(dc)
        mock_coupon.assert_called_once()
        call_kwargs = mock_coupon.call_args[1]
        self.assertEqual(call_kwargs['duration'], 'forever')
        self.assertNotIn('duration_in_months', call_kwargs)

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Coupon.create')
    def test_sync_discount_duration_once(self, mock_coupon, _cfg):
        from billing.stripe_service import sync_discount_to_stripe
        dc = InstituteDiscountCode.objects.create(
            code='ONCE50', discount_percent=50, duration='once',
        )
        mock_coupon.return_value = MagicMock(id='coupon_once')
        sync_discount_to_stripe(dc)
        call_kwargs = mock_coupon.call_args[1]
        self.assertEqual(call_kwargs['duration'], 'once')

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Coupon.create')
    def test_sync_discount_duration_repeating(self, mock_coupon, _cfg):
        from billing.stripe_service import sync_discount_to_stripe
        dc = InstituteDiscountCode.objects.create(
            code='REP50', discount_percent=50, duration='repeating', duration_in_months=6,
        )
        mock_coupon.return_value = MagicMock(id='coupon_rep')
        sync_discount_to_stripe(dc)
        call_kwargs = mock_coupon.call_args[1]
        self.assertEqual(call_kwargs['duration'], 'repeating')
        self.assertEqual(call_kwargs['duration_in_months'], 6)

    @patch('billing.stripe_service._stripe_configured', return_value=True)
    @patch('stripe.Coupon.create')
    def test_sync_individual_discount(self, mock_coupon, _cfg):
        from billing.stripe_service import sync_individual_discount_to_stripe
        dc = DiscountCode.objects.create(
            code='INDIV50', discount_percent=50, duration='repeating', duration_in_months=12,
        )
        mock_coupon.return_value = MagicMock(id='coupon_indiv')
        sync_individual_discount_to_stripe(dc)
        dc.refresh_from_db()
        self.assertEqual(dc.stripe_coupon_id, 'coupon_indiv')
        call_kwargs = mock_coupon.call_args[1]
        self.assertEqual(call_kwargs['duration'], 'repeating')
        self.assertEqual(call_kwargs['duration_in_months'], 12)


# ===========================================================================
# CPP-301: Unlimited packages display "0" → "Unlimited"
# ===========================================================================

class CPP301_UnlimitedDisplayTest(TestCase):
    """CPP-301: Verify that limit=0 fields display 'Unlimited' instead of '0'."""

    def setUp(self):
        self.superuser = _create_superuser('unlimsuper')
        self.client.login(username='unlimsuper', password='testpass123')
        self.unlimited_plan = _create_plan(
            name='Unlimited Plan', slug='unlimited',
            price=Decimal('999.00'),
            class_limit=0, student_limit=0, invoice_limit_yearly=0,
            stripe_price_id='price_test_unlimited',
        )
        self.school = _create_school(self.superuser, name='Unlim School', slug='unlim-school')
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.unlimited_plan, status='active',
        )

    def test_plan_list_shows_unlimited(self):
        resp = self.client.get(reverse('billing_admin_plan_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unlimited')
        self.assertNotContains(resp, '>0<', html=False)

    def test_subscription_list_shows_unlimited(self):
        resp = self.client.get(reverse('billing_admin_subscription_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unlimited')

    def test_subscription_detail_shows_unlimited(self):
        resp = self.client.get(reverse('billing_admin_subscription_detail', args=[self.sub.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unlimited')

    def test_upgrade_page_shows_unlimited(self):
        """The institute upgrade page should show 'Unlimited' for 0-limit plans."""
        hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.get_or_create(user=self.superuser, role=hoi_role)
        resp = self.client.get(reverse('institute_plan_upgrade'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unlimited')


# ===========================================================================
# Subscription Overview (students + institutes)
# ===========================================================================

class SubscriptionOverviewTests(TestCase):
    """Super-admin overview of how many students and institutes are subscribed."""

    def setUp(self):
        self.superuser = _create_superuser()
        self.normaluser = _create_normal_user()
        self.client.login(username='super', password='testpass123')

        # Individual student package + subscriptions:
        # 2 active + 1 trialing + 1 cancelled = total 4
        self.package = Package.objects.create(name='Student Monthly', price=Decimal('9.00'))
        for i, status in enumerate(['active', 'active', 'trialing', 'cancelled']):
            user = _create_normal_user(username=f'student{i}')
            user.country = 'New Zealand' if i == 0 else 'Australia'
            user.save(update_fields=['country'])
            Subscription.objects.create(user=user, package=self.package, status=status)

        # Institutes: 1 active + 1 trialing + 1 expired = total 3
        self.plan = _create_plan()  # 'Starter' @ $49
        for i, status in enumerate(['active', 'trialing', 'expired']):
            admin = _create_normal_user(username=f'schooladmin{i}')
            school = _create_school(admin, name=f'School {i}', slug=f'school-{i}')
            school.country = 'New Zealand' if i == 0 else 'Australia'
            school.save(update_fields=['country'])
            SchoolSubscription.objects.create(school=school, plan=self.plan, status=status)

    def _get(self, **params):
        return self.client.get(reverse('billing_admin_subscription_overview'), params)

    # -- access control --
    def test_normal_user_redirected(self):
        self.client.logout()
        self.client.login(username='normal', password='testpass123')
        self.assertEqual(self._get().status_code, 302)

    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self._get().status_code, 302)

    def test_superuser_can_access(self):
        self.assertEqual(self._get().status_code, 200)

    # -- layout: standalone, no sidebar --
    def test_renders_without_sidebar(self):
        resp = self._get()
        self.assertTrue(resp.context['hide_sidebar'])
        # sidebar partial is skipped, so its nav links are absent
        self.assertNotContains(resp, 'id="sidebar"')

    # -- student counts --
    def test_student_counts(self):
        s = self._get().context['students']
        self.assertEqual(s['total'], 4)
        self.assertEqual(s['active'], 2)
        self.assertEqual(s['paying'], 2)
        self.assertEqual(s['free'], 0)  # all setUp actives have a package
        self.assertEqual(s['trial'], 1)
        self.assertEqual(s['inactive'], 1)

    def test_student_new_today(self):
        # all created in setUp -> today
        self.assertEqual(self._get().context['students']['new_today'], 4)

    def test_student_lost_today(self):
        # cancelled status alone doesn't count; needs cancelled_at = today
        self.assertEqual(self._get().context['students']['lost_today'], 0)
        sub = Subscription.objects.filter(status='cancelled').first()
        sub.cancelled_at = timezone.now()
        sub.save(update_fields=['cancelled_at'])
        self.assertEqual(self._get().context['students']['lost_today'], 1)

    # -- institute counts --
    def test_institute_counts(self):
        inst = self._get().context['institutes']
        self.assertEqual(inst['total'], 3)
        self.assertEqual(inst['active'], 1)
        self.assertEqual(inst['paying'], 1)
        self.assertEqual(inst['free'], 0)
        self.assertEqual(inst['trial'], 1)
        self.assertEqual(inst['inactive'], 1)

    # -- paying counts --
    def test_paying_counts(self):
        ctx = self._get().context
        # 2 active students have a priced package ($9) -> 2 paying
        self.assertEqual(ctx['students']['paying'], 2)
        # 1 active institute on Starter ($49), no discount -> 1 paying
        self.assertEqual(ctx['institutes']['paying'], 1)

    def test_no_package_student_active_but_not_paying(self):
        user = _create_normal_user(username='free_student')
        Subscription.objects.create(user=user, package=None, status='active')
        ctx = self._get().context
        self.assertEqual(ctx['students']['active'], 3)  # active status total
        self.assertEqual(ctx['students']['paying'], 2)  # paying (priced package)
        self.assertEqual(ctx['students']['free'], 1)    # active but no package

    def test_full_discount_institute_not_paying(self):
        from billing.models import InstituteDiscountCode
        code = InstituteDiscountCode.objects.create(
            code='FREE100', discount_percent=100,
        )
        school = School.objects.filter(name='School 0').first()  # the active one
        sub = SchoolSubscription.objects.get(school=school)
        sub.discount_code = code
        sub.save(update_fields=['discount_code'])
        ctx = self._get().context
        self.assertEqual(ctx['institutes']['active'], 1)   # still active
        self.assertEqual(ctx['institutes']['paying'], 0)   # but fully discounted
        self.assertEqual(ctx['institutes']['free'], 1)     # shows as Free
        self.assertEqual(ctx['institutes']['estimate'], Decimal('0.00'))

    # -- earnings: estimate fallback (no Stripe key in tests) --
    def test_earnings_source_is_estimate_without_stripe(self):
        ctx = self._get().context
        self.assertEqual(ctx['earnings_source'], 'estimate')

    def test_student_estimate(self):
        s = self._get().context['students']
        self.assertEqual(s['estimate'], Decimal('18.00'))  # 2 active x $9

    def test_institute_estimate(self):
        inst = self._get().context['institutes']
        self.assertEqual(inst['estimate'], Decimal('49.00'))  # 1 active x $49

    def test_combined_estimate(self):
        self.assertEqual(self._get().context['combined_estimate'], Decimal('67.00'))

    def test_half_discount_institute_estimate(self):
        from billing.models import InstituteDiscountCode
        code = InstituteDiscountCode.objects.create(
            code='HALF50', discount_percent=50,
        )
        school = School.objects.filter(name='School 0').first()
        sub = SchoolSubscription.objects.get(school=school)
        sub.discount_code = code
        sub.save(update_fields=['discount_code'])
        inst = self._get().context['institutes']
        self.assertEqual(inst['estimate'], Decimal('24.50'))  # $49 * 50%
        self.assertEqual(inst['paying'], 1)                    # still paying (partial)

    # -- earnings: actual from Stripe (mocked) --
    @patch('billing.views_admin.get_paid_revenue')
    def test_earnings_from_stripe(self, mock_rev):
        mock_rev.side_effect = [
            {'student': Decimal('5.00'), 'institute': Decimal('7.00'),
             'student_count': 1, 'institute_count': 1, 'currency': 'NZD'},   # this month
            {'student': Decimal('3.00'), 'institute': Decimal('4.00'),
             'student_count': 1, 'institute_count': 1, 'currency': 'NZD'},   # last month
        ]
        ctx = self._get().context
        self.assertEqual(ctx['earnings_source'], 'stripe')
        self.assertEqual(ctx['earnings_currency'], 'NZD')
        self.assertEqual(ctx['students']['this_month'], Decimal('5.00'))
        self.assertEqual(ctx['students']['last_month'], Decimal('3.00'))
        self.assertEqual(ctx['institutes']['this_month'], Decimal('7.00'))
        self.assertEqual(ctx['combined_this_month'], Decimal('12.00'))

    # -- counts: live from Stripe (mocked) --
    @patch('billing.views_admin.get_subscription_counts')
    def test_counts_from_stripe(self, mock_counts):
        mock_counts.return_value = {
            'student': {'paid': 20, 'trial': 1, 'other': 2, 'total': 23},
            'institute': {'paid': 1, 'trial': 0, 'other': 0, 'total': 1},
        }
        ctx = self._get().context
        self.assertEqual(ctx['counts_source'], 'stripe')
        self.assertEqual(ctx['students']['stripe']['paid'], 20)
        self.assertEqual(ctx['institutes']['stripe']['paid'], 1)

    def test_counts_source_local_without_stripe(self):
        # No Stripe key in tests -> counts fall back to local DB
        self.assertEqual(self._get().context['counts_source'], 'local')

    # -- daily active graph (selectable window) --
    def test_daily_graph_default_window(self):
        ctx = self._get().context
        self.assertEqual(ctx['daily_window'], 30)
        self.assertEqual(len(ctx['daily']['labels']), 30)
        self.assertEqual(len(ctx['daily']['student']), 30)
        # setUp subs were created today -> last point reflects them (local fallback)
        self.assertEqual(ctx['daily']['student'][-1], 4)
        self.assertEqual(ctx['daily']['institute'][-1], 3)
        self.assertEqual(ctx['daily']['student'][0], 0)  # none existed 30 days ago

    def test_daily_graph_window_param(self):
        ctx = self._get(days='7').context
        self.assertEqual(ctx['daily_window'], 7)
        self.assertEqual(len(ctx['daily']['labels']), 7)

    def test_daily_graph_invalid_window_defaults_to_30(self):
        self.assertEqual(self._get(days='999').context['daily_window'], 30)

    def test_active_series_from_intervals(self):
        from billing.reporting import _active_series_from_intervals
        from datetime import timedelta
        today = timezone.localdate()
        intervals = [
            ('student', 'u1', today - timedelta(days=10), None),  # active all window
            ('student', 'u2', today - timedelta(days=2), None),   # active last 3 days
            # same student re-subscribed (overlapping) -> must NOT double-count
            ('student', 'u2', today - timedelta(days=1), None),
            ('institute', 's1', today - timedelta(days=5),
             today - timedelta(days=3)),                          # ended 3 days ago
        ]
        s = _active_series_from_intervals(intervals, 7)
        self.assertEqual(len(s['labels']), 7)
        self.assertEqual(s['student'][-1], 2)   # u1 & u2 distinct, today
        self.assertEqual(s['student'][0], 1)    # only u1 six days ago
        self.assertEqual(s['institute'][-1], 0)  # ended before today

    # -- breakdowns --
    def test_breakdowns(self):
        ctx = self._get().context
        packages = {r['package__name']: r['count'] for r in ctx['students']['by_package']}
        types = {r['plan__name']: r['count'] for r in ctx['institutes']['by_type']}
        self.assertEqual(packages.get('Student Monthly'), 2)  # active only
        self.assertEqual(types.get('Starter'), 1)             # active only

    # -- addons --
    def test_addons(self):
        from billing.models import ModuleProduct
        ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('10.00'),
        )
        active_sub = SchoolSubscription.objects.filter(status='active').first()
        ModuleSubscription.objects.create(
            school_subscription=active_sub, module='teachers_attendance', is_active=True,
        )
        ctx = self._get().context
        self.assertEqual(len(ctx['addons']), 1)
        self.assertEqual(ctx['addons'][0]['count'], 1)
        self.assertEqual(ctx['addons'][0]['revenue'], Decimal('10.00'))
        self.assertEqual(ctx['addons_total_revenue'], Decimal('10.00'))
        # addon revenue rolls into the institute estimate
        self.assertEqual(ctx['institutes']['estimate'], Decimal('59.00'))

    # -- filters --
    def test_country_filter(self):
        ctx = self._get(country='New Zealand').context
        # only 1 NZ student sub (active) and 1 NZ institute (active)
        self.assertEqual(ctx['students']['total'], 1)
        self.assertEqual(ctx['institutes']['total'], 1)
        self.assertIn('New Zealand', ctx['filters']['countries'])

    def test_institution_filter(self):
        school = _create_school(
            _create_normal_user(username='solo_admin'),
            name='Solo School', slug='solo-school',
        )
        SchoolSubscription.objects.create(school=school, plan=self.plan, status='active')
        ctx = self._get(institution=str(school.id)).context
        self.assertEqual(ctx['institutes']['total'], 1)
        self.assertEqual(ctx['institutes']['active'], 1)

    def test_page_renders_sections(self):
        resp = self._get()
        self.assertContains(resp, 'Student Subscriptions')
        self.assertContains(resp, 'Institute Subscriptions')
        self.assertContains(resp, 'Institution Add-ons')

    def test_auto_refresh_present(self):
        resp = self._get()
        self.assertEqual(resp.context['refresh_seconds'], 60)
        self.assertContains(resp, 'auto-refreshes every')
        self.assertContains(resp, 'window.location.reload()')

    # -- B2C exclusion: institute students must NOT count as student subs --
    def test_institute_students_excluded_from_student_panel(self):
        # Baseline: 4 B2C student subs from setUp
        self.assertEqual(self._get().context['students']['total'], 4)

        # An institute student: has a Subscription AND an active SchoolStudent row
        school = School.objects.filter(name='School 0').first()
        inst_user = _create_normal_user(username='inst_student')
        SchoolStudent.objects.create(
            school=school, student=inst_user, is_active=True,
        )
        Subscription.objects.create(
            user=inst_user, package=self.package, status='active',
        )

        # Still 4 — the institute student is excluded from the B2C panel
        s = self._get().context['students']
        self.assertEqual(s['total'], 4)
        self.assertEqual(s['active'], 2)  # unchanged, not 3

    def test_former_institute_student_counts_as_b2c(self):
        # If the school membership is inactive, they're B2C again
        school = School.objects.filter(name='School 0').first()
        user = _create_normal_user(username='left_school')
        SchoolStudent.objects.create(school=school, student=user, is_active=False)
        Subscription.objects.create(user=user, package=self.package, status='active')
        self.assertEqual(self._get().context['students']['total'], 5)

    # -- deactivated schools must not appear anywhere on the dashboard --
    def test_deactivated_schools_excluded(self):
        # Baseline: 3 institute subs from setUp (all active schools)
        self.assertEqual(self._get().context['institutes']['total'], 3)

        # Deactivate "School 0" (which has an active subscription)
        school = School.objects.filter(name='School 0').first()
        school.is_active = False
        school.save(update_fields=['is_active'])

        ctx = self._get().context
        inst = ctx['institutes']
        self.assertEqual(inst['total'], 2)   # School 0 dropped
        self.assertEqual(inst['active'], 0)  # School 0 was the only active one
        # and it's gone from the institution filter dropdown
        names = [i['name'] for i in ctx['filters']['institutions']]
        self.assertNotIn('School 0', names)

    # -- status donut --
    def test_student_donut_segments(self):
        donut = self._get().context['students']['donut']
        labels = {s['label']: s['value'] for s in donut['segments']}
        # 2 paying (Active), 0 free, 1 trial, 1 inactive
        self.assertEqual(labels, {'Active': 2, 'Free': 0, 'Trial': 1, 'Inactive': 1})
        self.assertEqual(donut['total'], 4)
        self.assertEqual(donut['active_pct'], 50.0)  # 2 paying of 4

    def test_donut_renders_svg(self):
        resp = self._get()
        self.assertContains(resp, 'Student status')
        self.assertContains(resp, 'Institute status')
        self.assertContains(resp, 'stroke-dasharray')

    def test_donut_handles_zero_total(self):
        Subscription.objects.all().delete()
        donut = self._get().context['students']['donut']
        self.assertEqual(donut['total'], 0)
        self.assertEqual(donut['active_pct'], 0.0)
        # all segments present but zero-valued (template skips rendering them)
        self.assertEqual(len(donut['segments']), 4)


class StripeEarningsReportingTests(TestCase):
    """billing.reporting.get_paid_revenue — attribution + fallback."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        pkg = Package.objects.create(name='Wizard', price=Decimal('19.90'))
        u = _create_normal_user(username='paycust')
        Subscription.objects.create(
            user=u, package=pkg, status='active', stripe_customer_id='cus_student',
        )
        admin = _create_normal_user(username='payadmin')
        school = _create_school(admin, name='Pay School', slug='pay-school')
        SchoolSubscription.objects.create(
            school=school, plan=_create_plan(), status='active',
            stripe_customer_id='cus_inst',
        )

    def test_no_stripe_key_raises_unavailable(self):
        from billing.reporting import get_paid_revenue, StripeUnavailable
        import datetime
        start = timezone.make_aware(datetime.datetime(2026, 5, 1))
        end = timezone.make_aware(datetime.datetime(2026, 6, 1))
        with override_settings(STRIPE_SECRET_KEY=''):
            with self.assertRaises(StripeUnavailable):
                get_paid_revenue(start, end)

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    @patch('billing.reporting.stripe.Invoice.list')
    def test_attribution_by_customer(self, mock_list):
        from billing.reporting import get_paid_revenue
        import datetime
        sub = 'subscription_cycle'
        invoices = [
            {'amount_paid': 1990, 'customer': 'cus_student', 'billing_reason': sub, 'currency': 'nzd'},
            {'amount_paid': 9450, 'customer': 'cus_inst', 'billing_reason': sub, 'currency': 'nzd'},
            {'amount_paid': 500, 'customer': 'cus_unknown', 'billing_reason': sub, 'currency': 'nzd'},  # not ours
            {'amount_paid': 0, 'customer': 'cus_student', 'billing_reason': sub, 'currency': 'nzd'},     # zero
            {'amount_paid': 5000, 'customer': 'cus_inst', 'billing_reason': 'manual', 'currency': 'nzd'},  # not a sub
        ]
        obj = MagicMock()
        obj.auto_paging_iter.return_value = iter(invoices)
        mock_list.return_value = obj
        start = timezone.make_aware(datetime.datetime(2026, 5, 1))
        end = timezone.make_aware(datetime.datetime(2026, 6, 1))
        res = get_paid_revenue(start, end)
        self.assertEqual(res['student'], Decimal('19.90'))
        self.assertEqual(res['institute'], Decimal('94.50'))  # manual $50 excluded
        self.assertEqual(res['student_count'], 1)
        self.assertEqual(res['institute_count'], 1)
        self.assertEqual(res['currency'], 'NZD')

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    @patch('billing.reporting.stripe.Subscription.list')
    def test_subscription_counts(self, mock_list):
        from billing.reporting import get_subscription_counts
        from django.core.cache import cache
        cache.clear()
        subs = [
            {'metadata': {'type': 'individual', 'user_id': '1'}, 'status': 'active'},
            {'metadata': {'type': 'school_student', 'user_id': '2'}, 'status': 'active'},
            {'metadata': {'type': 'individual', 'user_id': '3'}, 'status': 'trialing'},
            {'metadata': {'type': 'institute', 'school_id': '9'}, 'status': 'active'},
            # duplicate subscription for the SAME school -> must dedupe to 1
            {'metadata': {'type': 'institute', 'school_id': '9'}, 'status': 'active'},
            {'metadata': {'type': 'institute', 'school_id': '8'}, 'status': 'canceled'},
            {'metadata': {'type': 'module'}, 'status': 'active'},   # ignored
            {'metadata': {}, 'status': 'active'},                    # untyped, ignored
        ]
        obj = MagicMock()
        obj.auto_paging_iter.return_value = iter(subs)
        mock_list.return_value = obj
        c = get_subscription_counts()
        # students = distinct individual + school_student users
        self.assertEqual(c['student']['paid'], 2)   # users 1 & 2
        self.assertEqual(c['student']['trial'], 1)  # user 3
        self.assertEqual(c['student']['total'], 3)
        # institutes deduped by school_id: school 9 (2 subs) counts once
        self.assertEqual(c['institute']['paid'], 1)
        self.assertEqual(c['institute']['other'], 1)   # school 8 canceled
        self.assertEqual(c['institute']['total'], 2)   # schools 9 & 8
