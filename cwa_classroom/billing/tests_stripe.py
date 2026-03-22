"""
Comprehensive tests for Stripe integration.

Tests stripe_service.py functions, webhook_handlers.py handlers,
and Stripe-related views. All Stripe API calls are mocked using
unittest.mock.patch.
"""
import time
from decimal import Decimal
from unittest.mock import patch, MagicMock, call

from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan,
    SchoolSubscription,
    ModuleSubscription,
    Package,
    Subscription,
    StripeEvent,
)
from classroom.models import School, SchoolTeacher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(path='/'):
    factory = RequestFactory()
    request = factory.get(path)
    request.META['HTTP_HOST'] = 'localhost'
    request.META['SERVER_PORT'] = '8000'
    return request


# ---------------------------------------------------------------------------
# Base TestCase with common fixtures
# ---------------------------------------------------------------------------

class StripeTestBase(TestCase):
    """Shared setUp for all Stripe test classes."""

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.admin_role, _ = Role.objects.get_or_create(
            name='admin',
            defaults={'display_name': 'Admin'},
        )
        cls.institute_owner_role, _ = Role.objects.get_or_create(
            name='institute_owner',
            defaults={'display_name': 'Institute Owner'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name='student',
            defaults={'display_name': 'Student'},
        )

        # Plans -- use get_or_create with slug to avoid conflicts with seed data
        cls.plan_basic, _ = InstitutePlan.objects.get_or_create(
            slug='test-basic',
            defaults={
                'name': 'Test Basic',
                'price': Decimal('49.00'),
                'stripe_price_id': 'price_test_basic_123',
                'class_limit': 5,
                'student_limit': 50,
                'invoice_limit_yearly': 100,
                'extra_invoice_rate': Decimal('2.00'),
                'trial_days': 14,
                'is_active': True,
            },
        )
        cls.plan_pro, _ = InstitutePlan.objects.get_or_create(
            slug='test-pro',
            defaults={
                'name': 'Test Pro',
                'price': Decimal('99.00'),
                'stripe_price_id': 'price_test_pro_456',
                'class_limit': 20,
                'student_limit': 200,
                'invoice_limit_yearly': 500,
                'extra_invoice_rate': Decimal('1.50'),
                'trial_days': 14,
                'is_active': True,
            },
        )
        cls.plan_no_stripe, _ = InstitutePlan.objects.get_or_create(
            slug='test-no-stripe',
            defaults={
                'name': 'Test No Stripe',
                'price': Decimal('29.00'),
                'stripe_price_id': '',
                'class_limit': 3,
                'student_limit': 20,
                'invoice_limit_yearly': 50,
                'extra_invoice_rate': Decimal('3.00'),
                'is_active': True,
            },
        )

        # Package for individual students
        cls.package = Package.objects.create(
            name='Test Student Package',
            class_limit=3,
            price=Decimal('19.00'),
            stripe_price_id='price_student_pkg_789',
            billing_type=Package.BILLING_RECURRING,
            is_active=True,
        )

        # Users
        cls.admin_user = CustomUser.objects.create_user(
            username='testadmin',
            email='admin@test.com',
            password='testpass123',
        )
        UserRole.objects.get_or_create(user=cls.admin_user, role=cls.institute_owner_role)

        cls.student_user = CustomUser.objects.create_user(
            username='teststudent',
            email='student@test.com',
            password='testpass123',
        )

        # School
        cls.school = School.objects.create(
            name='Test School',
            slug='test-school',
            admin=cls.admin_user,
        )

        # SchoolTeacher link
        SchoolTeacher.objects.get_or_create(
            school=cls.school,
            teacher=cls.admin_user,
            defaults={'role': 'head_of_institute'},
        )

    def _create_school_subscription(self, **kwargs):
        defaults = {
            'school': self.school,
            'plan': self.plan_basic,
            'status': SchoolSubscription.STATUS_TRIALING,
            'stripe_customer_id': '',
            'stripe_subscription_id': '',
        }
        defaults.update(kwargs)
        sub, _ = SchoolSubscription.objects.update_or_create(
            school=defaults.pop('school'),
            defaults=defaults,
        )
        return sub

    def _create_individual_subscription(self, user=None, **kwargs):
        user = user or self.student_user
        defaults = {
            'user': user,
            'package': self.package,
            'status': Subscription.STATUS_TRIALING,
            'stripe_customer_id': '',
            'stripe_subscription_id': '',
        }
        defaults.update(kwargs)
        sub, _ = Subscription.objects.update_or_create(
            user=defaults.pop('user'),
            defaults=defaults,
        )
        return sub


# ===========================================================================
# stripe_service.py -- get_or_create_customer
# ===========================================================================

class GetOrCreateCustomerTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.Customer.create')
    def test_returns_existing_customer_id_for_school(self, mock_create):
        sub = self._create_school_subscription(stripe_customer_id='cus_existing_school')
        result = self._call(school=self.school)
        self.assertEqual(result, 'cus_existing_school')
        mock_create.assert_not_called()

    @patch('billing.stripe_service.stripe.Customer.create')
    def test_creates_customer_for_school_without_id(self, mock_create):
        sub = self._create_school_subscription(stripe_customer_id='')
        mock_create.return_value = MagicMock(id='cus_new_school')

        result = self._call(school=self.school)

        self.assertEqual(result, 'cus_new_school')
        mock_create.assert_called_once()
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_new_school')

    @patch('billing.stripe_service.stripe.Customer.create')
    def test_returns_existing_customer_id_for_user(self, mock_create):
        sub = self._create_individual_subscription(stripe_customer_id='cus_existing_user')
        result = self._call(user=self.student_user)
        self.assertEqual(result, 'cus_existing_user')
        mock_create.assert_not_called()

    @patch('billing.stripe_service.stripe.Customer.create')
    def test_creates_customer_for_user_without_id(self, mock_create):
        sub = self._create_individual_subscription(stripe_customer_id='')
        mock_create.return_value = MagicMock(id='cus_new_user')

        result = self._call(user=self.student_user)

        self.assertEqual(result, 'cus_new_user')
        mock_create.assert_called_once()
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_new_user')

    def test_raises_value_error_with_no_args(self):
        from billing.stripe_service import get_or_create_customer
        with self.assertRaises(ValueError):
            get_or_create_customer()

    # helper
    def _call(self, **kwargs):
        from billing.stripe_service import get_or_create_customer
        return get_or_create_customer(**kwargs)


# ===========================================================================
# stripe_service.py -- create_institute_checkout_session
# ===========================================================================

class CreateInstituteCheckoutSessionTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_school_abc')
    def test_creates_session_with_correct_params(self, mock_customer, mock_session_create):
        mock_session_create.return_value = MagicMock(url='https://checkout.stripe.com/xyz')
        request = _make_request()

        from billing.stripe_service import create_institute_checkout_session
        session = create_institute_checkout_session(self.school, self.plan_basic, request)

        self.assertEqual(session.url, 'https://checkout.stripe.com/xyz')
        mock_customer.assert_called_once_with(school=self.school)

        call_kwargs = mock_session_create.call_args[1]
        self.assertEqual(call_kwargs['customer'], 'cus_school_abc')
        self.assertEqual(call_kwargs['mode'], 'subscription')
        self.assertEqual(call_kwargs['line_items'], [{'price': 'price_test_basic_123', 'quantity': 1}])
        self.assertIn('checkout/success', call_kwargs['success_url'])
        self.assertIn('plans', call_kwargs['cancel_url'])
        self.assertEqual(call_kwargs['metadata']['type'], 'institute')
        self.assertEqual(call_kwargs['metadata']['school_id'], self.school.id)

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_school_abc')
    def test_passes_trial_period_days_when_provided(self, mock_customer, mock_session_create):
        mock_session_create.return_value = MagicMock(url='https://checkout.stripe.com/trial')
        request = _make_request()

        from billing.stripe_service import create_institute_checkout_session
        create_institute_checkout_session(self.school, self.plan_basic, request, trial_period_days=14)

        call_kwargs = mock_session_create.call_args[1]
        self.assertIn('trial_period_days', call_kwargs['subscription_data'])
        self.assertEqual(call_kwargs['subscription_data']['trial_period_days'], 14)

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_school_abc')
    def test_omits_trial_period_days_when_none(self, mock_customer, mock_session_create):
        mock_session_create.return_value = MagicMock(url='https://checkout.stripe.com/notrial')
        request = _make_request()

        from billing.stripe_service import create_institute_checkout_session
        create_institute_checkout_session(self.school, self.plan_basic, request, trial_period_days=None)

        call_kwargs = mock_session_create.call_args[1]
        self.assertNotIn('trial_period_days', call_kwargs['subscription_data'])


# ===========================================================================
# stripe_service.py -- create_individual_checkout_session
# ===========================================================================

class CreateIndividualCheckoutSessionTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_user_abc')
    def test_creates_session_for_individual(self, mock_customer, mock_session_create):
        mock_session_create.return_value = MagicMock(url='https://checkout.stripe.com/ind')
        request = _make_request()

        from billing.stripe_service import create_individual_checkout_session
        session = create_individual_checkout_session(self.student_user, self.package, request)

        self.assertEqual(session.url, 'https://checkout.stripe.com/ind')
        mock_customer.assert_called_once_with(user=self.student_user)

        call_kwargs = mock_session_create.call_args[1]
        self.assertEqual(call_kwargs['customer'], 'cus_user_abc')
        self.assertEqual(call_kwargs['line_items'], [{'price': 'price_student_pkg_789', 'quantity': 1}])
        self.assertEqual(call_kwargs['metadata']['type'], 'individual')
        self.assertEqual(call_kwargs['metadata']['user_id'], self.student_user.id)
        self.assertEqual(call_kwargs['metadata']['package_id'], self.package.id)


# ===========================================================================
# stripe_service.py -- change_institute_plan
# ===========================================================================

class ChangeInstitutePlanTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.Subscription.modify')
    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_changes_plan_successfully(self, mock_retrieve, mock_modify):
        sub = self._create_school_subscription(stripe_subscription_id='sub_test_123')

        plan_item = MagicMock()
        plan_item.id = 'si_plan_item_1'
        plan_item.__getitem__ = lambda self, k: {} if k == 'metadata' else None
        plan_item.get = lambda k, d=None: {} if k == 'metadata' else d

        mock_retrieve.return_value = {
            'items': {'data': [plan_item]},
        }

        from billing.stripe_service import change_institute_plan
        result = change_institute_plan(sub, self.plan_pro)

        self.assertTrue(result)
        mock_modify.assert_called_once()
        modify_kwargs = mock_modify.call_args
        self.assertEqual(modify_kwargs[0][0], 'sub_test_123')
        self.assertEqual(modify_kwargs[1]['proration_behavior'], 'create_prorations')

        sub.refresh_from_db()
        self.assertEqual(sub.plan, self.plan_pro)

    def test_raises_if_no_stripe_subscription_id(self):
        sub = self._create_school_subscription(stripe_subscription_id='')
        from billing.stripe_service import change_institute_plan
        with self.assertRaises(ValueError) as ctx:
            change_institute_plan(sub, self.plan_pro)
        self.assertIn('No active Stripe subscription', str(ctx.exception))

    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_raises_if_no_plan_item_found(self, mock_retrieve):
        sub = self._create_school_subscription(stripe_subscription_id='sub_test_456')

        # All items are module type
        module_item = MagicMock()
        module_item.__getitem__ = lambda self, k: {'type': 'module'} if k == 'metadata' else None
        module_item.get = lambda k, d=None: {'type': 'module'} if k == 'metadata' else d

        mock_retrieve.return_value = {
            'items': {'data': [module_item]},
        }

        from billing.stripe_service import change_institute_plan
        with self.assertRaises(ValueError) as ctx:
            change_institute_plan(sub, self.plan_pro)
        self.assertIn('Cannot find plan item', str(ctx.exception))


# ===========================================================================
# stripe_service.py -- add_module_to_subscription
# ===========================================================================

class AddModuleToSubscriptionTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.SubscriptionItem.create')
    def test_adds_module_successfully(self, mock_si_create):
        sub = self._create_school_subscription(stripe_subscription_id='sub_mod_123')
        mock_si_create.return_value = MagicMock(id='si_module_new')

        from billing.stripe_service import add_module_to_subscription
        item = add_module_to_subscription(sub, 'teachers_attendance', 'price_module_ta')

        self.assertEqual(item.id, 'si_module_new')
        mock_si_create.assert_called_once()
        call_kwargs = mock_si_create.call_args[1]
        self.assertEqual(call_kwargs['subscription'], 'sub_mod_123')
        self.assertEqual(call_kwargs['price'], 'price_module_ta')
        self.assertEqual(call_kwargs['metadata']['type'], 'module')
        self.assertEqual(call_kwargs['metadata']['module'], 'teachers_attendance')

        # Check local ModuleSubscription was created
        mod_sub = ModuleSubscription.objects.get(
            school_subscription=sub,
            module='teachers_attendance',
        )
        self.assertTrue(mod_sub.is_active)
        self.assertEqual(mod_sub.stripe_subscription_item_id, 'si_module_new')

    def test_raises_if_no_stripe_subscription_id(self):
        sub = self._create_school_subscription(stripe_subscription_id='')
        from billing.stripe_service import add_module_to_subscription
        with self.assertRaises(ValueError):
            add_module_to_subscription(sub, 'teachers_attendance', 'price_x')


# ===========================================================================
# stripe_service.py -- remove_module_from_subscription
# ===========================================================================

class RemoveModuleFromSubscriptionTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.SubscriptionItem.delete')
    def test_removes_module_successfully(self, mock_si_delete):
        sub = self._create_school_subscription(stripe_subscription_id='sub_rm_123')
        ModuleSubscription.objects.create(
            school_subscription=sub,
            module='teachers_attendance',
            stripe_subscription_item_id='si_ta_old',
            is_active=True,
        )

        from billing.stripe_service import remove_module_from_subscription
        result = remove_module_from_subscription(sub, 'teachers_attendance')

        self.assertTrue(result)
        mock_si_delete.assert_called_once_with(
            'si_ta_old',
            proration_behavior='create_prorations',
        )

        mod_sub = ModuleSubscription.objects.get(
            school_subscription=sub,
            module='teachers_attendance',
        )
        self.assertFalse(mod_sub.is_active)
        self.assertIsNotNone(mod_sub.deactivated_at)

    def test_returns_false_if_module_not_found(self):
        sub = self._create_school_subscription(stripe_subscription_id='sub_rm_456')
        from billing.stripe_service import remove_module_from_subscription
        result = remove_module_from_subscription(sub, 'nonexistent_module')
        self.assertFalse(result)


# ===========================================================================
# stripe_service.py -- cancel_subscription
# ===========================================================================

class CancelSubscriptionTest(StripeTestBase):

    @patch('billing.stripe_service.stripe.Subscription.modify')
    def test_cancel_at_period_end(self, mock_modify):
        from billing.stripe_service import cancel_subscription
        cancel_subscription('sub_cancel_123', at_period_end=True)

        mock_modify.assert_called_once_with(
            'sub_cancel_123',
            cancel_at_period_end=True,
        )

    @patch('billing.stripe_service.stripe.Subscription.cancel')
    def test_cancel_immediately(self, mock_cancel):
        from billing.stripe_service import cancel_subscription
        cancel_subscription('sub_cancel_456', at_period_end=False)

        mock_cancel.assert_called_once_with('sub_cancel_456')


# ===========================================================================
# webhook_handlers.py -- handle_checkout_completed
# ===========================================================================

class HandleCheckoutCompletedTest(StripeTestBase):

    def test_activates_institute_subscription(self):
        sub = self._create_school_subscription(
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end=timezone.now(),
        )
        event_data = {
            'object': {
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                    'plan_id': str(self.plan_basic.id),
                },
                'subscription': 'sub_checkout_inst',
            },
        }

        from billing.webhook_handlers import handle_checkout_completed
        handle_checkout_completed(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertEqual(sub.stripe_subscription_id, 'sub_checkout_inst')
        self.assertIsNone(sub.trial_end)

    def test_activates_individual_subscription(self):
        sub = self._create_individual_subscription(
            status=Subscription.STATUS_TRIALING,
        )
        event_data = {
            'object': {
                'metadata': {
                    'type': 'individual',
                    'user_id': str(self.student_user.id),
                    'package_id': str(self.package.id),
                },
                'subscription': 'sub_checkout_ind',
            },
        }

        from billing.webhook_handlers import handle_checkout_completed
        handle_checkout_completed(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.stripe_subscription_id, 'sub_checkout_ind')

        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.package, self.package)


# ===========================================================================
# webhook_handlers.py -- handle_subscription_updated
# ===========================================================================

class HandleSubscriptionUpdatedTest(StripeTestBase):

    def _make_event_data(self, sub_type, status, stripe_sub_id, metadata_extra=None,
                         cancel_at_period_end=False):
        now_ts = int(time.time())
        metadata = {'type': sub_type}
        if metadata_extra:
            metadata.update(metadata_extra)
        return {
            'object': {
                'id': stripe_sub_id,
                'status': status,
                'metadata': metadata,
                'cancel_at_period_end': cancel_at_period_end,
                'current_period_start': now_ts,
                'current_period_end': now_ts + 30 * 86400,
            },
        }

    def test_maps_active_status_for_institute(self):
        sub = self._create_school_subscription(stripe_subscription_id='sub_upd_inst')
        event_data = self._make_event_data(
            'institute', 'active', 'sub_upd_inst',
            metadata_extra={'school_id': str(self.school.id)},
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_ACTIVE)

    def test_maps_trialing_status_for_institute(self):
        sub = self._create_school_subscription(stripe_subscription_id='sub_upd_trial')
        event_data = self._make_event_data(
            'institute', 'trialing', 'sub_upd_trial',
            metadata_extra={'school_id': str(self.school.id)},
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)

    def test_maps_past_due_status_for_institute(self):
        sub = self._create_school_subscription(stripe_subscription_id='sub_upd_pd')
        event_data = self._make_event_data(
            'institute', 'past_due', 'sub_upd_pd',
            metadata_extra={'school_id': str(self.school.id)},
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_PAST_DUE)

    def test_maps_canceled_status_for_institute(self):
        sub = self._create_school_subscription(stripe_subscription_id='sub_upd_canc')
        event_data = self._make_event_data(
            'institute', 'canceled', 'sub_upd_canc',
            metadata_extra={'school_id': str(self.school.id)},
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_CANCELLED)

    def test_updates_period_dates_for_institute(self):
        sub = self._create_school_subscription(stripe_subscription_id='sub_upd_dates')
        event_data = self._make_event_data(
            'institute', 'active', 'sub_upd_dates',
            metadata_extra={'school_id': str(self.school.id)},
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertIsNotNone(sub.current_period_start)
        self.assertIsNotNone(sub.current_period_end)

    def test_individual_cancel_at_period_end(self):
        sub = self._create_individual_subscription(
            stripe_subscription_id='sub_upd_ind_cancel',
        )
        event_data = self._make_event_data(
            'individual', 'active', 'sub_upd_ind_cancel',
            metadata_extra={'user_id': str(self.student_user.id)},
            cancel_at_period_end=True,
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)

    def test_individual_sets_cancelled_at_on_canceled(self):
        sub = self._create_individual_subscription(
            stripe_subscription_id='sub_upd_ind_cancelled',
        )
        event_data = self._make_event_data(
            'individual', 'canceled', 'sub_upd_ind_cancelled',
            metadata_extra={'user_id': str(self.student_user.id)},
        )

        from billing.webhook_handlers import handle_subscription_updated
        handle_subscription_updated(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_CANCELLED)
        self.assertIsNotNone(sub.cancelled_at)


# ===========================================================================
# webhook_handlers.py -- handle_subscription_deleted
# ===========================================================================

class HandleSubscriptionDeletedTest(StripeTestBase):

    def test_marks_subscription_as_cancelled(self):
        sub = self._create_school_subscription(
            stripe_subscription_id='sub_del_inst',
            status=SchoolSubscription.STATUS_ACTIVE,
        )
        event_data = {
            'object': {
                'id': 'sub_del_inst',
                'status': 'active',  # original status before deletion
                'metadata': {
                    'type': 'institute',
                    'school_id': str(self.school.id),
                },
                'cancel_at_period_end': False,
                'current_period_start': int(time.time()),
                'current_period_end': int(time.time()) + 30 * 86400,
            },
        }

        from billing.webhook_handlers import handle_subscription_deleted
        handle_subscription_deleted(event_data)

        sub.refresh_from_db()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_CANCELLED)


# ===========================================================================
# webhook_handlers.py -- handle_payment_succeeded / handle_payment_failed
# ===========================================================================

class HandlePaymentEventsTest(StripeTestBase):

    @patch('audit.services.log_event')
    def test_payment_succeeded_logs_event(self, mock_log):
        event_data = {
            'object': {
                'subscription': 'sub_pay_ok',
                'amount_paid': 4900,
                'currency': 'nzd',
            },
        }

        from billing.webhook_handlers import handle_payment_succeeded
        handle_payment_succeeded(event_data)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        self.assertEqual(call_kwargs['category'], 'billing')
        self.assertEqual(call_kwargs['action'], 'payment_succeeded')
        self.assertEqual(call_kwargs['detail']['amount_cents'], 4900)

    @patch('audit.services.log_event')
    def test_payment_failed_logs_event(self, mock_log):
        event_data = {
            'object': {
                'subscription': 'sub_pay_fail',
                'customer': 'cus_fail_123',
                'amount_due': 9900,
                'currency': 'nzd',
            },
        }

        from billing.webhook_handlers import handle_payment_failed
        handle_payment_failed(event_data)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        self.assertEqual(call_kwargs['category'], 'billing')
        self.assertEqual(call_kwargs['action'], 'payment_failed')
        self.assertEqual(call_kwargs['result'], 'blocked')
        self.assertEqual(call_kwargs['detail']['amount_cents'], 9900)
        self.assertEqual(call_kwargs['detail']['stripe_customer_id'], 'cus_fail_123')


# ===========================================================================
# Views -- InstituteCheckoutView
# ===========================================================================

@override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_PUBLISHABLE_KEY='pk_test_fake')
class InstituteCheckoutViewTest(StripeTestBase):

    def setUp(self):
        self.client.login(username='testadmin', password='testpass123')
        # Ensure school subscription exists
        self._create_school_subscription()

    @patch('billing.views.get_school_for_user')
    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.stripe.Customer.create')
    def test_creates_checkout_and_redirects(self, mock_cust_create, mock_sess_create, mock_get_school):
        mock_get_school.return_value = self.school
        mock_cust_create.return_value = MagicMock(id='cus_view_test')
        mock_sess_create.return_value = MagicMock(url='https://checkout.stripe.com/view_test')

        response = self.client.post(
            reverse('institute_checkout'),
            {'plan': 'test-basic'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://checkout.stripe.com/view_test')

    @patch('billing.views.get_school_for_user')
    def test_error_for_plan_without_stripe_price_id(self, mock_get_school):
        mock_get_school.return_value = self.school

        response = self.client.post(
            reverse('institute_checkout'),
            {'plan': 'test-no-stripe'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/billing/institute/plans/', response.url)

    def test_error_for_invalid_plan(self):
        response = self.client.post(
            reverse('institute_checkout'),
            {'plan': 'nonexistent-plan'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/billing/institute/plans/', response.url)


# ===========================================================================
# Views -- InstituteChangePlanView
# ===========================================================================

@override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_PUBLISHABLE_KEY='pk_test_fake')
class InstituteChangePlanViewTest(StripeTestBase):

    def setUp(self):
        self.client.login(username='testadmin', password='testpass123')

    @patch('billing.views.get_school_for_user')
    @patch('billing.views.get_school_subscription')
    @patch('billing.stripe_service.stripe.Subscription.modify')
    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_changes_plan_and_redirects(self, mock_retrieve, mock_modify,
                                         mock_get_sub, mock_get_school):
        sub = self._create_school_subscription(stripe_subscription_id='sub_change_view')
        mock_get_school.return_value = self.school
        mock_get_sub.return_value = sub

        plan_item = MagicMock()
        plan_item.id = 'si_plan_view_1'
        plan_item.__getitem__ = lambda self, k: {} if k == 'metadata' else None
        plan_item.get = lambda k, d=None: {} if k == 'metadata' else d

        mock_retrieve.return_value = {'items': {'data': [plan_item]}}

        response = self.client.post(
            reverse('institute_change_plan'),
            {'plan': 'test-pro'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/billing/institute/dashboard/', response.url)
        mock_modify.assert_called_once()

    @patch('billing.views.get_school_for_user')
    @patch('billing.views.get_school_subscription')
    def test_error_if_no_stripe_subscription_id(self, mock_get_sub, mock_get_school):
        sub = self._create_school_subscription(stripe_subscription_id='')
        mock_get_school.return_value = self.school
        mock_get_sub.return_value = sub

        response = self.client.post(
            reverse('institute_change_plan'),
            {'plan': 'test-pro'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/billing/institute/plans/', response.url)


# ===========================================================================
# Views -- InstituteCancelSubscriptionView
# ===========================================================================

@override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_PUBLISHABLE_KEY='pk_test_fake')
class InstituteCancelSubscriptionViewTest(StripeTestBase):

    def setUp(self):
        self.client.login(username='testadmin', password='testpass123')

    @patch('billing.views.get_school_for_user')
    @patch('billing.views.get_school_subscription')
    @patch('billing.stripe_service.stripe.Subscription.modify')
    def test_cancels_subscription_and_redirects(self, mock_modify, mock_get_sub, mock_get_school):
        sub = self._create_school_subscription(stripe_subscription_id='sub_cancel_view')
        mock_get_school.return_value = self.school
        mock_get_sub.return_value = sub

        response = self.client.post(reverse('institute_cancel_subscription'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/billing/institute/dashboard/', response.url)
        mock_modify.assert_called_once_with(
            'sub_cancel_view',
            cancel_at_period_end=True,
        )

    @patch('billing.views.get_school_for_user')
    @patch('billing.views.get_school_subscription')
    def test_error_if_no_subscription(self, mock_get_sub, mock_get_school):
        mock_get_school.return_value = self.school
        mock_get_sub.return_value = None

        response = self.client.post(reverse('institute_cancel_subscription'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/billing/institute/dashboard/', response.url)
