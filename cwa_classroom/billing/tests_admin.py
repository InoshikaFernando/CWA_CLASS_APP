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
    SchoolSubscription, PromoCode,
)
from classroom.models import School


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
