"""
Every platform subscription is charged in USD.

Nothing in the checkout call names a currency: Stripe Prices are immutable and
carry their own, so whichever Price is attached to a Package/InstitutePlan/
ModuleProduct decides what the card is charged. A $19 package once pointed at
an NZD 19 price and a student was charged NZD 19 instead of USD 19 — and
nothing noticed, because a Stripe subscription's currency cannot be changed
afterwards, only cancelled and recreated.

These tests pin the two ends of that: prices are always *created* in USD, and a
non-USD price is refused before any Checkout Session exists.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, ModuleProduct, Package
from billing.stripe_service import (
    SUBSCRIPTION_CURRENCY,
    assert_subscription_price_currency,
)


def _request(path='/'):
    request = RequestFactory().get(path)
    request.META['HTTP_HOST'] = 'localhost'
    request.META['SERVER_PORT'] = '8000'
    return request


def _price(currency='usd', price_id='price_x'):
    return SimpleNamespace(id=price_id, currency=currency)


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class AssertSubscriptionPriceCurrencyTests(TestCase):

    @patch('billing.stripe_service.stripe.Price.retrieve')
    def test_usd_price_passes(self, mock_retrieve):
        mock_retrieve.return_value = _price('usd')
        result = assert_subscription_price_currency('price_usd', 'Package "Wizards"')
        self.assertEqual(result.currency, 'usd')
        mock_retrieve.assert_called_once_with('price_usd')

    @patch('billing.stripe_service.stripe.Price.retrieve')
    def test_uppercase_currency_passes(self, mock_retrieve):
        mock_retrieve.return_value = _price('USD')
        assert_subscription_price_currency('price_usd', 'Package "Wizards"')

    @patch('billing.stripe_service.stripe.Price.retrieve')
    def test_nzd_price_is_refused_and_names_the_currency(self, mock_retrieve):
        mock_retrieve.return_value = _price('nzd', 'price_nzd_19')
        with self.assertRaises(ValueError) as ctx:
            assert_subscription_price_currency('price_nzd_19', 'Package "Wizards"')
        message = str(ctx.exception)
        self.assertIn('NZD', message)
        self.assertIn('USD', message)
        self.assertIn('price_nzd_19', message)

    @patch('billing.stripe_service.stripe.Price.retrieve')
    def test_blank_price_id_is_refused_without_calling_stripe(self, mock_retrieve):
        with self.assertRaises(ValueError):
            assert_subscription_price_currency('', 'Package "Wizards"')
        mock_retrieve.assert_not_called()

    def test_subscription_currency_is_usd(self):
        self.assertEqual(SUBSCRIPTION_CURRENCY, 'usd')

    def test_there_is_no_env_currency_setting(self):
        """The .env knob is what made an NZD price in the first place; it is
        gone deliberately, so nothing can re-point subscriptions at NZD."""
        self.assertFalse(hasattr(settings, 'STRIPE_CURRENCY'))


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class CheckoutRefusesNonUsdPriceTests(TestCase):
    """No Checkout Session may be created against a non-USD price."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username='cur_student', email='cur_student@test.com',
            password='testpass123',
        )
        cls.package = Package.objects.create(
            name='Wizards Student', class_limit=0, price=Decimal('19.00'),
            stripe_price_id='price_nzd_19', is_active=True,
        )
        cls.plan = InstitutePlan.objects.create(
            name='Basic', slug='cur-basic', price=Decimal('89.00'),
            stripe_price_id='price_nzd_89', class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )

    def setUp(self):
        patcher = patch('billing.stripe_service.stripe.Price.retrieve',
                        return_value=_price('nzd'))
        self.mock_retrieve = patcher.start()
        self.addCleanup(patcher.stop)

        session_patcher = patch('billing.stripe_service.stripe.checkout.Session.create')
        self.mock_session_create = session_patcher.start()
        self.addCleanup(session_patcher.stop)

    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_x')
    def test_school_student_checkout_refused(self, _customer):
        from billing.stripe_service import create_student_checkout_session
        with self.assertRaises(ValueError):
            create_student_checkout_session(self.user, self.package, _request())
        self.mock_session_create.assert_not_called()

    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_x')
    def test_individual_checkout_refused(self, _customer):
        from billing.stripe_service import create_individual_checkout_session
        with self.assertRaises(ValueError):
            create_individual_checkout_session(self.user, self.package, _request())
        self.mock_session_create.assert_not_called()

    def test_pending_registration_checkout_refused(self):
        from billing.stripe_service import create_pending_registration_checkout_session
        with self.assertRaises(ValueError):
            create_pending_registration_checkout_session(
                'new@test.com', self.package, _request(),
            )
        self.mock_session_create.assert_not_called()

    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_school')
    def test_institute_checkout_refused(self, _customer):
        from classroom.models import School
        from billing.stripe_service import create_institute_checkout_session
        school = School.objects.create(
            name='Cur School', slug='cur-school', admin=self.user,
        )
        with self.assertRaises(ValueError):
            create_institute_checkout_session(school, self.plan, _request())
        self.mock_session_create.assert_not_called()

    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_x')
    def test_usd_price_still_checks_out(self, _customer):
        from billing.stripe_service import create_student_checkout_session
        self.mock_retrieve.return_value = _price('usd')
        self.mock_session_create.return_value = MagicMock(url='https://checkout/ok')

        session = create_student_checkout_session(self.user, self.package, _request())

        self.assertEqual(session.url, 'https://checkout/ok')
        call_kwargs = self.mock_session_create.call_args[1]
        self.assertEqual(
            call_kwargs['line_items'], [{'price': 'price_nzd_19', 'quantity': 1}],
        )


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class CheckoutViewSurfacesCurrencyErrorTests(TestCase):
    """The student sees an error rather than a charge in the wrong currency."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='cur_buyer', email='cur_buyer@test.com', password='testpass123',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        UserRole.objects.create(user=self.user, role=role)
        self.package = Package.objects.create(
            name='Wizards Student', class_limit=0, price=Decimal('19.00'),
            stripe_price_id='price_nzd_19', is_active=True,
        )

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.stripe.Price.retrieve', return_value=_price('nzd'))
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_x')
    def test_non_usd_package_does_not_reach_stripe_checkout(
        self, _customer, _retrieve, mock_session_create,
    ):
        self.client.login(username='cur_buyer', password='testpass123')

        resp = self.client.get(reverse('billing_checkout', args=[self.package.id]))

        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('checkout.stripe.com', resp.url)
        mock_session_create.assert_not_called()


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class SyncToStripeCreatesUsdPricesTests(TestCase):

    @patch('billing.stripe_service.stripe.Price.modify')
    @patch('billing.stripe_service.stripe.Price.create')
    @patch('billing.stripe_service.stripe.Product.retrieve')
    @patch('billing.stripe_service.stripe.Product.modify')
    def test_plan_price_created_in_usd(self, _modify, mock_retrieve, mock_create, _pmodify):
        from billing.stripe_service import sync_plan_to_stripe
        plan = InstitutePlan.objects.create(
            name='Basic', slug='usd-basic', price=Decimal('89.00'),
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        mock_retrieve.return_value = SimpleNamespace(id='prod_x')
        mock_create.return_value = SimpleNamespace(id='price_new')

        sync_plan_to_stripe(plan)

        self.assertEqual(mock_create.call_args[1]['currency'], 'usd')
        plan.refresh_from_db()
        self.assertEqual(plan.stripe_price_id, 'price_new')

    @patch('billing.stripe_service.stripe.Price.modify')
    @patch('billing.stripe_service.stripe.Price.create')
    @patch('billing.stripe_service.stripe.Product.retrieve')
    @patch('billing.stripe_service.stripe.Product.modify')
    def test_module_price_created_in_usd(self, _modify, mock_retrieve, mock_create, _pmodify):
        from billing.stripe_service import sync_module_to_stripe
        module = ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('10.00'), is_active=True,
        )
        mock_retrieve.return_value = SimpleNamespace(id='prod_m')
        mock_create.return_value = SimpleNamespace(id='price_mod')

        sync_module_to_stripe(module)

        self.assertEqual(mock_create.call_args[1]['currency'], 'usd')
