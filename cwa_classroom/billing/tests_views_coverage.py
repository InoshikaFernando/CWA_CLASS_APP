"""
Tests for billing/views.py, billing/mixins.py, and audit/risk.py
to increase coverage beyond current levels (34%, 63%, 33%).
"""
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from billing.models import (
    InstitutePlan, ModuleSubscription, Package, Payment,
    SchoolSubscription, Subscription,
)
from classroom.models import School, SchoolStudent, SchoolTeacher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name, display_name=None):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_hoi_with_school(username='hoi', plan_status='active'):
    user = CustomUser.objects.create_user(
        username=username, password='testpass123', email=f'{username}@test.com',
    )
    role = _create_role(Role.HEAD_OF_INSTITUTE)
    UserRole.objects.create(user=user, role=role)
    school = School.objects.create(
        name=f'{username} School', slug=f'{username}-school', admin=user,
    )
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{username}', price=Decimal('89.00'),
        stripe_price_id='price_test', class_limit=5, student_limit=100,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status=plan_status)
    return user, school, plan, sub


def _create_package(name='Pro', price=Decimal('19.90'), is_active=True):
    return Package.objects.create(
        name=name, price=price, stripe_price_id='price_pkg_test', is_active=is_active,
    )


# ===========================================================================
# billing/views.py tests
# ===========================================================================

class CheckoutViewTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='buyer', password='testpass123', email='buyer@test.com',
        )
        self.package = _create_package()

    def test_get_renders_checkout(self):
        self.client.login(username='buyer', password='testpass123')
        resp = self.client.get(reverse('billing_checkout', args=[self.package.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('package', resp.context)
        self.assertEqual(resp.context['package'], self.package)

    def test_get_404_for_inactive_package(self):
        self.package.is_active = False
        self.package.save()
        self.client.login(username='buyer', password='testpass123')
        resp = self.client.get(reverse('billing_checkout', args=[self.package.id]))
        self.assertEqual(resp.status_code, 404)

    def test_requires_login(self):
        resp = self.client.get(reverse('billing_checkout', args=[self.package.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)


class CreatePaymentIntentViewTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='buyer', password='testpass123', email='buyer@test.com',
        )
        self.package = _create_package()
        self.client.login(username='buyer', password='testpass123')

    def test_free_package_returns_400(self):
        free_pkg = _create_package(name='Free', price=Decimal('0.00'))
        resp = self.client.post(
            reverse('create_payment_intent', args=[free_pkg.id]),
            data=json.dumps({}), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    @patch('billing.views.stripe.PaymentIntent.create')
    @patch('billing.views.stripe.Customer.create')
    def test_creates_customer_and_intent(self, mock_cust, mock_intent):
        mock_cust.return_value = MagicMock(id='cus_test123')
        mock_intent.return_value = MagicMock(client_secret='pi_secret_test')
        resp = self.client.post(
            reverse('create_payment_intent', args=[self.package.id]),
            data=json.dumps({}), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['client_secret'], 'pi_secret_test')
        mock_cust.assert_called_once()

    @patch('billing.views.stripe.PaymentIntent.create')
    def test_uses_existing_customer_id(self, mock_intent):
        Subscription.objects.create(
            user=self.user, package=self.package, stripe_customer_id='cus_existing',
        )
        mock_intent.return_value = MagicMock(client_secret='pi_secret_existing')
        resp = self.client.post(
            reverse('create_payment_intent', args=[self.package.id]),
            data=json.dumps({}), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['client_secret'], 'pi_secret_existing')

    @patch('billing.views.stripe.PaymentIntent.create')
    @patch('billing.views.stripe.Customer.create')
    def test_stripe_error_returns_400(self, mock_cust, mock_intent):
        mock_cust.return_value = MagicMock(id='cus_test')
        import stripe as stripe_mod
        mock_intent.side_effect = stripe_mod.error.StripeError('fail')
        resp = self.client.post(
            reverse('create_payment_intent', args=[self.package.id]),
            data=json.dumps({}), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class ConfirmPaymentViewTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='buyer', password='testpass123', email='buyer@test.com',
        )
        self.package = _create_package()
        self.client.login(username='buyer', password='testpass123')

    def test_missing_params_returns_400(self):
        resp = self.client.post(
            reverse('confirm_payment'),
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('billing.views.stripe.PaymentIntent.retrieve')
    def test_payment_not_succeeded_returns_400(self, mock_retrieve):
        mock_retrieve.return_value = MagicMock(status='requires_payment_method')
        resp = self.client.post(
            reverse('confirm_payment'),
            data=json.dumps({'payment_intent_id': 'pi_test', 'package_id': self.package.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('billing.views.stripe.PaymentIntent.retrieve')
    def test_successful_payment(self, mock_retrieve):
        mock_retrieve.return_value = MagicMock(status='succeeded')
        resp = self.client.post(
            reverse('confirm_payment'),
            data=json.dumps({'payment_intent_id': 'pi_ok', 'package_id': self.package.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        self.assertTrue(Payment.objects.filter(stripe_payment_intent_id='pi_ok').exists())
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)

    @patch('billing.views.stripe.PaymentIntent.retrieve')
    def test_stripe_error_returns_400(self, mock_retrieve):
        import stripe as stripe_mod
        mock_retrieve.side_effect = stripe_mod.error.StripeError('bad')
        resp = self.client.post(
            reverse('confirm_payment'),
            data=json.dumps({'payment_intent_id': 'pi_bad', 'package_id': self.package.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class InstitutePlanSelectViewTest(TestCase):
    def test_no_school_redirects(self):
        user = CustomUser.objects.create_user(
            username='nobody', password='testpass123', email='nobody@test.com',
        )
        self.client.login(username='nobody', password='testpass123')
        resp = self.client.get(reverse('institute_plan_select'))
        self.assertEqual(resp.status_code, 302)

    def test_with_school_renders(self):
        user, school, plan, sub = _create_hoi_with_school()
        self.client.login(username='hoi', password='testpass123')
        resp = self.client.get(reverse('institute_plan_select'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('plans', resp.context)
        self.assertEqual(resp.context['school'], school)
        self.assertEqual(resp.context['current_plan'], plan)


class InstitutePlanUpgradeViewTest(TestCase):
    def test_no_school_redirects(self):
        user = CustomUser.objects.create_user(
            username='nobody2', password='testpass123', email='nobody2@test.com',
        )
        self.client.login(username='nobody2', password='testpass123')
        resp = self.client.get(reverse('institute_plan_upgrade'))
        self.assertEqual(resp.status_code, 302)

    def test_with_school_renders(self):
        user, school, plan, sub = _create_hoi_with_school(username='upgrade_hoi')
        self.client.login(username='upgrade_hoi', password='testpass123')
        resp = self.client.get(reverse('institute_plan_upgrade'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('invoices_used', resp.context)
        self.assertIn('overage_rate', resp.context)


class InstituteSubscriptionDashboardViewTest(TestCase):
    def test_no_school_redirects(self):
        user = CustomUser.objects.create_user(
            username='noschool', password='testpass123', email='noschool@test.com',
        )
        self.client.login(username='noschool', password='testpass123')
        resp = self.client.get(reverse('institute_subscription_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_no_subscription_redirects_to_plan_select(self):
        user = CustomUser.objects.create_user(
            username='nosub', password='testpass123', email='nosub@test.com',
        )
        role = _create_role(Role.HEAD_OF_INSTITUTE)
        UserRole.objects.create(user=user, role=role)
        School.objects.create(name='NoSub School', slug='nosub-school', admin=user)
        self.client.login(username='nosub', password='testpass123')
        resp = self.client.get(reverse('institute_subscription_dashboard'))
        self.assertRedirects(resp, reverse('institute_plan_select'), fetch_redirect_response=False)

    def test_with_subscription_renders_dashboard(self):
        user, school, plan, sub = _create_hoi_with_school(username='dash_hoi')
        self.client.login(username='dash_hoi', password='testpass123')
        resp = self.client.get(reverse('institute_subscription_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('class_limit', resp.context)
        self.assertIn('active_modules', resp.context)


class ModuleRequiredViewTest(TestCase):
    def test_renders_with_module_slug(self):
        user = CustomUser.objects.create_user(
            username='moduser', password='testpass123', email='moduser@test.com',
        )
        self.client.login(username='moduser', password='testpass123')
        resp = self.client.get(reverse('module_required') + '?module=teachers_attendance')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['module_slug'], 'teachers_attendance')
        self.assertEqual(resp.context['module_name'], 'Teachers Attendance')

    def test_renders_with_unknown_module(self):
        user = CustomUser.objects.create_user(
            username='moduser2', password='testpass123', email='moduser2@test.com',
        )
        self.client.login(username='moduser2', password='testpass123')
        resp = self.client.get(reverse('module_required') + '?module=unknown_mod')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['module_name'], 'Unknown Mod')


class InstituteCheckoutSuccessViewTest(TestCase):
    def test_renders_success_page(self):
        user, school, plan, sub = _create_hoi_with_school(username='succ_hoi')
        self.client.login(username='succ_hoi', password='testpass123')
        resp = self.client.get(reverse('institute_checkout_success'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['school'], school)

    def test_renders_without_school(self):
        user = CustomUser.objects.create_user(
            username='noschool_succ', password='testpass123', email='noschool_succ@test.com',
        )
        self.client.login(username='noschool_succ', password='testpass123')
        resp = self.client.get(reverse('institute_checkout_success'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['school'])


class InstituteCancelSubscriptionViewTest(TestCase):
    def test_no_school_redirects(self):
        user = CustomUser.objects.create_user(
            username='cancel_noschool', password='testpass123', email='cn@test.com',
        )
        self.client.login(username='cancel_noschool', password='testpass123')
        resp = self.client.post(reverse('institute_cancel_subscription'))
        self.assertEqual(resp.status_code, 302)

    def test_no_stripe_sub_shows_error(self):
        user, school, plan, sub = _create_hoi_with_school(username='cancel_nosub')
        # No stripe_subscription_id set
        self.client.login(username='cancel_nosub', password='testpass123')
        resp = self.client.post(reverse('institute_cancel_subscription'))
        self.assertEqual(resp.status_code, 302)

    @patch('billing.stripe_service.cancel_subscription')
    def test_successful_cancellation(self, mock_cancel):
        user, school, plan, sub = _create_hoi_with_school(username='cancel_ok')
        sub.stripe_subscription_id = 'sub_stripe_123'
        sub.save()
        self.client.login(username='cancel_ok', password='testpass123')
        resp = self.client.post(reverse('institute_cancel_subscription'))
        self.assertEqual(resp.status_code, 302)

    @patch('billing.stripe_service.cancel_subscription')
    def test_stripe_error_on_cancel(self, mock_cancel):
        import stripe as stripe_mod
        mock_cancel.side_effect = stripe_mod.error.StripeError('cancel fail')
        user, school, plan, sub = _create_hoi_with_school(username='cancel_err')
        sub.stripe_subscription_id = 'sub_stripe_err'
        sub.save()
        self.client.login(username='cancel_err', password='testpass123')
        resp = self.client.post(reverse('institute_cancel_subscription'))
        self.assertEqual(resp.status_code, 302)


class StripeBillingPortalViewTest(TestCase):
    def test_no_customer_redirects(self):
        user = CustomUser.objects.create_user(
            username='portal_no', password='testpass123', email='portal_no@test.com',
        )
        self.client.login(username='portal_no', password='testpass123')
        resp = self.client.get(reverse('stripe_billing_portal'))
        self.assertEqual(resp.status_code, 302)

    @patch('billing.stripe_service.create_billing_portal_session')
    def test_redirects_to_portal(self, mock_portal):
        mock_session = MagicMock()
        mock_session.url = 'https://billing.stripe.com/portal/test'
        mock_portal.return_value = mock_session
        user, school, plan, sub = _create_hoi_with_school(username='portal_hoi')
        sub.stripe_customer_id = 'cus_portal_test'
        sub.save()
        self.client.login(username='portal_hoi', password='testpass123')
        resp = self.client.get(reverse('stripe_billing_portal'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, 'https://billing.stripe.com/portal/test')

    @patch('billing.stripe_service.create_billing_portal_session')
    def test_stripe_error_redirects(self, mock_portal):
        import stripe as stripe_mod
        mock_portal.side_effect = stripe_mod.error.StripeError('portal fail')
        user, school, plan, sub = _create_hoi_with_school(username='portal_err')
        sub.stripe_customer_id = 'cus_portal_err'
        sub.save()
        self.client.login(username='portal_err', password='testpass123')
        resp = self.client.get(reverse('stripe_billing_portal'))
        self.assertEqual(resp.status_code, 302)

    def test_fallback_to_individual_subscription(self):
        """When no school customer, falls back to individual subscription customer_id."""
        user = CustomUser.objects.create_user(
            username='portal_ind', password='testpass123', email='portal_ind@test.com',
        )
        pkg = _create_package(name='IndPkg')
        Subscription.objects.create(
            user=user, package=pkg, stripe_customer_id='cus_individual',
        )
        self.client.login(username='portal_ind', password='testpass123')
        with patch('billing.stripe_service.create_billing_portal_session') as mock_portal:
            mock_session = MagicMock()
            mock_session.url = 'https://billing.stripe.com/portal/ind'
            mock_portal.return_value = mock_session
            resp = self.client.get(reverse('stripe_billing_portal'))
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.url, 'https://billing.stripe.com/portal/ind')


@override_settings(MODULE_STRIPE_PRICES={
    'teachers_attendance': 'price_ta_test',
    'students_attendance': 'price_sa_test',
})
class ModuleToggleViewTest(TestCase):
    def setUp(self):
        self.user, self.school, self.plan, self.sub = _create_hoi_with_school(
            username='mod_toggle',
        )
        self.sub.stripe_subscription_id = 'sub_toggle_123'
        self.sub.save()
        from billing.models import ModuleProduct
        mp, _ = ModuleProduct.objects.get_or_create(
            module='teachers_attendance',
            defaults={
                'name': 'Teachers Attendance',
                'stripe_price_id': 'price_test_teachers_att',
                'price': 10.00,
            },
        )
        if not mp.stripe_price_id:
            mp.stripe_price_id = 'price_test_teachers_att'
            mp.save()
        self.client.login(username='mod_toggle', password='testpass123')

    def test_invalid_module_shows_error(self):
        resp = self.client.post(reverse('module_toggle'), {'module': 'nonexistent', 'action': 'add'})
        self.assertEqual(resp.status_code, 302)

    def test_no_school_redirects(self):
        user2 = CustomUser.objects.create_user(
            username='mod_no_school', password='testpass123', email='mns@test.com',
        )
        self.client.login(username='mod_no_school', password='testpass123')
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'add'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_no_subscription_redirects_to_plan_select(self):
        user2 = CustomUser.objects.create_user(
            username='mod_no_sub', password='testpass123', email='mnosub@test.com',
        )
        role = _create_role(Role.HEAD_OF_INSTITUTE)
        UserRole.objects.create(user=user2, role=role)
        School.objects.create(name='NoSub2 School', slug='nosub2-school', admin=user2)
        self.client.login(username='mod_no_sub', password='testpass123')
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'add'},
        )
        self.assertRedirects(resp, reverse('institute_plan_select'), fetch_redirect_response=False)

    @patch('billing.stripe_service.add_module_to_subscription')
    def test_add_module_success(self, mock_add):
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'add'},
        )
        self.assertEqual(resp.status_code, 302)
        mock_add.assert_called_once()

    @patch('billing.stripe_service.remove_module_from_subscription')
    def test_remove_module_success(self, mock_remove):
        mock_remove.return_value = True
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'remove'},
        )
        self.assertEqual(resp.status_code, 302)
        mock_remove.assert_called_once()

    @patch('billing.stripe_service.remove_module_from_subscription')
    def test_remove_module_not_active(self, mock_remove):
        mock_remove.return_value = False
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'remove'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_invalid_action(self):
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'invalid'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_add_module_no_price_configured(self):
        with self.settings(MODULE_STRIPE_PRICES={}):
            resp = self.client.post(
                reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'add'},
            )
            self.assertEqual(resp.status_code, 302)

    @patch('billing.stripe_service.add_module_to_subscription')
    def test_add_module_stripe_error(self, mock_add):
        import stripe as stripe_mod
        mock_add.side_effect = stripe_mod.error.StripeError('module fail')
        resp = self.client.post(
            reverse('module_toggle'), {'module': 'teachers_attendance', 'action': 'add'},
        )
        self.assertEqual(resp.status_code, 302)


class BillingHistoryViewTest(TestCase):
    def test_with_school_subscription(self):
        user, school, plan, sub = _create_hoi_with_school(username='hist_hoi')
        self.client.login(username='hist_hoi', password='testpass123')
        resp = self.client.get(reverse('billing_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['school'], school)
        self.assertIsNone(resp.context['individual_sub'])

    def test_with_individual_subscription(self):
        user = CustomUser.objects.create_user(
            username='hist_ind', password='testpass123', email='hist_ind@test.com',
        )
        pkg = _create_package(name='IndPkg2')
        Subscription.objects.create(user=user, package=pkg)
        self.client.login(username='hist_ind', password='testpass123')
        resp = self.client.get(reverse('billing_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['school'])
        self.assertIsNotNone(resp.context['individual_sub'])

    def test_no_subscriptions(self):
        user = CustomUser.objects.create_user(
            username='hist_none', password='testpass123', email='hist_none@test.com',
        )
        self.client.login(username='hist_none', password='testpass123')
        resp = self.client.get(reverse('billing_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['school'])
        self.assertIsNone(resp.context['individual_sub'])


# ===========================================================================
# billing/mixins.py tests
# ===========================================================================

class SchoolResolverMixinTest(TestCase):
    """Tests for _SchoolResolverMixin._resolve_school."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_resolve_from_url_kwargs(self):
        from billing.mixins import _SchoolResolverMixin
        user, school, _, _ = _create_hoi_with_school(username='resolver_url')
        request = self.factory.get('/')
        request.user = user
        request.session = {}
        mixin = _SchoolResolverMixin()
        result = mixin._resolve_school(request, school_id=school.pk)
        self.assertEqual(result, school)

    def test_resolve_from_url_kwargs_invalid_id(self):
        from billing.mixins import _SchoolResolverMixin
        user = CustomUser.objects.create_user(
            username='resolver_bad', password='testpass123', email='rb@test.com',
        )
        request = self.factory.get('/')
        request.user = user
        request.session = {}
        mixin = _SchoolResolverMixin()
        result = mixin._resolve_school(request, school_id=99999)
        # Falls through to get_school_for_user which returns None
        self.assertIsNone(result)

    def test_resolve_from_session(self):
        from billing.mixins import _SchoolResolverMixin
        user, school, _, _ = _create_hoi_with_school(username='resolver_sess')
        request = self.factory.get('/')
        request.user = user
        request.session = {'current_school_id': school.pk}
        mixin = _SchoolResolverMixin()
        result = mixin._resolve_school(request)
        self.assertEqual(result, school)

    def test_resolve_from_session_invalid_id(self):
        from billing.mixins import _SchoolResolverMixin
        user, school, _, _ = _create_hoi_with_school(username='resolver_sess_bad')
        request = self.factory.get('/')
        request.user = user
        request.session = {'current_school_id': 99999}
        mixin = _SchoolResolverMixin()
        # Falls through to get_school_for_user
        result = mixin._resolve_school(request)
        self.assertEqual(result, school)  # Found via admin role

    def test_resolve_fallback_to_user(self):
        from billing.mixins import _SchoolResolverMixin
        user, school, _, _ = _create_hoi_with_school(username='resolver_fb')
        request = self.factory.get('/')
        request.user = user
        request.session = {}
        mixin = _SchoolResolverMixin()
        result = mixin._resolve_school(request)
        self.assertEqual(result, school)


class PlanRequiredMixinTest(TestCase):
    """Tests for PlanRequiredMixin dispatch logic."""

    def test_expired_subscription_blocks_access(self):
        """When sub is expired and no other school is active, user is redirected."""
        user, school, plan, sub = _create_hoi_with_school(
            username='plan_expired', plan_status='expired',
        )
        self.client.login(username='plan_expired', password='testpass123')
        # Access a view protected by PlanRequiredMixin - we test via the mixin directly
        from billing.mixins import PlanRequiredMixin
        from django.views import View
        from django.http import HttpResponse

        class DummyView(PlanRequiredMixin, View):
            def get(self, request):
                return HttpResponse('ok')

        factory = RequestFactory()
        request = factory.get('/')
        request.user = user
        request.session = {}
        # Add message storage
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        view = DummyView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('trial-expired', resp.url)

    def test_active_subscription_allows_access(self):
        user, school, plan, sub = _create_hoi_with_school(
            username='plan_active', plan_status='active',
        )
        from billing.mixins import PlanRequiredMixin
        from django.views import View
        from django.http import HttpResponse

        class DummyView(PlanRequiredMixin, View):
            def get(self, request):
                return HttpResponse('ok')

        factory = RequestFactory()
        request = factory.get('/')
        request.user = user
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        view = DummyView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 200)


class ModuleRequiredMixinTest(TestCase):
    """Tests for ModuleRequiredMixin dispatch logic."""

    def test_missing_module_redirects(self):
        user, school, plan, sub = _create_hoi_with_school(username='mod_miss')
        from billing.mixins import ModuleRequiredMixin
        from django.views import View
        from django.http import HttpResponse

        class DummyView(ModuleRequiredMixin, View):
            required_module = 'teachers_attendance'

            def get(self, request):
                return HttpResponse('ok')

        factory = RequestFactory()
        request = factory.get('/')
        request.user = user
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        view = DummyView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('module-required', resp.url)
        self.assertIn('teachers_attendance', resp.url)

    def test_module_present_allows_access(self):
        user, school, plan, sub = _create_hoi_with_school(username='mod_pres')
        ModuleSubscription.objects.create(
            school_subscription=sub, module='teachers_attendance', is_active=True,
        )
        from billing.mixins import ModuleRequiredMixin
        from django.views import View
        from django.http import HttpResponse

        class DummyView(ModuleRequiredMixin, View):
            required_module = 'teachers_attendance'

            def get(self, request):
                return HttpResponse('ok')

        factory = RequestFactory()
        request = factory.get('/')
        request.user = user
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        view = DummyView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 200)

    def test_no_required_module_allows_access(self):
        """When required_module is None, mixin doesn't block."""
        user, school, plan, sub = _create_hoi_with_school(username='mod_none')
        from billing.mixins import ModuleRequiredMixin
        from django.views import View
        from django.http import HttpResponse

        class DummyView(ModuleRequiredMixin, View):
            required_module = None

            def get(self, request):
                return HttpResponse('ok')

        factory = RequestFactory()
        request = factory.get('/')
        request.user = user
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        view = DummyView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# audit/risk.py tests
# ===========================================================================

class DetectTrialAbuseTest(TestCase):
    def test_no_abuse_returns_empty(self):
        from audit.risk import detect_trial_abuse
        result = detect_trial_abuse()
        self.assertEqual(result, [])

    def test_detects_multiple_users_same_ip(self):
        from audit.risk import detect_trial_abuse
        users = []
        for i in range(4):
            u = CustomUser.objects.create_user(
                username=f'abuser{i}', password='testpass123', email=f'abuser{i}@test.com',
            )
            users.append(u)
            AuditLog.objects.create(
                user=u, category='auth', action='login_success',
                ip_address='192.168.1.100',
            )
        result = detect_trial_abuse(days=30, ip_threshold=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['ip_address'], '192.168.1.100')
        self.assertEqual(result[0]['user_count'], 4)
        self.assertEqual(result[0]['risk_level'], 'medium')

    def test_high_risk_level(self):
        from audit.risk import detect_trial_abuse
        for i in range(6):
            u = CustomUser.objects.create_user(
                username=f'highrisk{i}', password='testpass123', email=f'hr{i}@test.com',
            )
            AuditLog.objects.create(
                user=u, category='auth', action='login_success',
                ip_address='10.0.0.1',
            )
        result = detect_trial_abuse(days=30, ip_threshold=3)
        flagged = [r for r in result if r['ip_address'] == '10.0.0.1']
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]['risk_level'], 'high')

    def test_below_threshold_not_flagged(self):
        from audit.risk import detect_trial_abuse
        for i in range(2):
            u = CustomUser.objects.create_user(
                username=f'below{i}', password='testpass123', email=f'below{i}@test.com',
            )
            AuditLog.objects.create(
                user=u, category='auth', action='login_success',
                ip_address='172.16.0.1',
            )
        result = detect_trial_abuse(days=30, ip_threshold=3)
        ips = [r['ip_address'] for r in result]
        self.assertNotIn('172.16.0.1', ips)


class DetectRapidLoginFailuresTest(TestCase):
    def test_no_failures_returns_empty(self):
        from audit.risk import detect_rapid_login_failures
        result = detect_rapid_login_failures()
        self.assertEqual(result, [])

    def test_detects_rapid_failures(self):
        from audit.risk import detect_rapid_login_failures
        for i in range(7):
            AuditLog.objects.create(
                category='auth', action='login_failed', ip_address='10.10.10.10',
            )
        result = detect_rapid_login_failures(threshold=5, window_minutes=15)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['ip_address'], '10.10.10.10')
        self.assertEqual(result[0]['failure_count'], 7)
        self.assertEqual(result[0]['risk_level'], 'high')

    def test_critical_risk_level(self):
        from audit.risk import detect_rapid_login_failures
        for _ in range(12):
            AuditLog.objects.create(
                category='auth', action='login_failed', ip_address='10.10.10.11',
            )
        result = detect_rapid_login_failures(threshold=5, window_minutes=15)
        flagged = [r for r in result if r['ip_address'] == '10.10.10.11']
        self.assertEqual(flagged[0]['risk_level'], 'critical')

    def test_below_threshold_not_flagged(self):
        from audit.risk import detect_rapid_login_failures
        for _ in range(3):
            AuditLog.objects.create(
                category='auth', action='login_failed', ip_address='10.10.10.12',
            )
        result = detect_rapid_login_failures(threshold=5, window_minutes=15)
        ips = [r['ip_address'] for r in result]
        self.assertNotIn('10.10.10.12', ips)


class DetectPaymentFailurePatternTest(TestCase):
    def test_no_failures_returns_empty(self):
        from audit.risk import detect_payment_failure_pattern
        result = detect_payment_failure_pattern()
        self.assertEqual(result, [])

    def test_detects_repeated_payment_failures(self):
        from audit.risk import detect_payment_failure_pattern
        for _ in range(4):
            AuditLog.objects.create(
                category='billing', action='payment_failed',
                detail={'stripe_subscription_id': 'sub_failing'},
            )
        result = detect_payment_failure_pattern(threshold=3, days=30)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['stripe_subscription_id'], 'sub_failing')
        self.assertEqual(result[0]['risk_level'], 'medium')

    def test_high_risk_level(self):
        from audit.risk import detect_payment_failure_pattern
        for _ in range(6):
            AuditLog.objects.create(
                category='billing', action='payment_failed',
                detail={'stripe_subscription_id': 'sub_high'},
            )
        result = detect_payment_failure_pattern(threshold=3, days=30)
        flagged = [r for r in result if r['stripe_subscription_id'] == 'sub_high']
        self.assertEqual(flagged[0]['risk_level'], 'high')


class DetectModuleAbuseTest(TestCase):
    def test_no_abuse_returns_empty(self):
        from audit.risk import detect_module_abuse
        result = detect_module_abuse()
        self.assertEqual(result, [])

    def test_detects_repeated_module_access_denied(self):
        from audit.risk import detect_module_abuse
        user = CustomUser.objects.create_user(
            username='mod_abuser', password='testpass123', email='ma@test.com',
        )
        for _ in range(25):
            AuditLog.objects.create(
                user=user, category='entitlement', action='module_access_denied',
            )
        result = detect_module_abuse(threshold=20, window_minutes=60)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['username'], 'mod_abuser')
        self.assertEqual(result[0]['risk_level'], 'medium')

    def test_below_threshold_not_flagged(self):
        from audit.risk import detect_module_abuse
        user = CustomUser.objects.create_user(
            username='mod_low', password='testpass123', email='ml@test.com',
        )
        for _ in range(5):
            AuditLog.objects.create(
                user=user, category='entitlement', action='module_access_denied',
            )
        result = detect_module_abuse(threshold=20, window_minutes=60)
        self.assertEqual(len(result), 0)


class GetRiskSummaryTest(TestCase):
    def test_empty_summary(self):
        from audit.risk import get_risk_summary
        summary = get_risk_summary()
        self.assertEqual(summary['login_failures_24h'], 0)
        self.assertEqual(summary['rate_limited_24h'], 0)
        self.assertEqual(summary['module_denials_7d'], 0)
        self.assertEqual(summary['payment_failures_7d'], 0)
        self.assertEqual(summary['blocked_access_7d'], 0)
        self.assertEqual(summary['subscription_expired_7d'], 0)

    def test_summary_counts_events(self):
        from audit.risk import get_risk_summary
        AuditLog.objects.create(category='auth', action='login_failed')
        AuditLog.objects.create(category='auth', action='login_failed')
        AuditLog.objects.create(category='auth', action='login_rate_limited')
        AuditLog.objects.create(category='entitlement', action='module_access_denied')
        AuditLog.objects.create(category='billing', action='payment_failed')
        AuditLog.objects.create(category='auth', action='blocked_user_access_attempt')
        AuditLog.objects.create(category='entitlement', action='subscription_expired_access')
        summary = get_risk_summary()
        self.assertEqual(summary['login_failures_24h'], 2)
        self.assertEqual(summary['rate_limited_24h'], 1)
        self.assertEqual(summary['module_denials_7d'], 1)
        self.assertEqual(summary['payment_failures_7d'], 1)
        self.assertEqual(summary['blocked_access_7d'], 1)
        self.assertEqual(summary['subscription_expired_7d'], 1)
