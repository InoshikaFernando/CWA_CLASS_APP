"""Half price for the first year on AI Question Import, applied automatically.

The plans page quotes the first-year price. Until this existed, nothing in the
add-module path applied a discount — ``add_module_to_subscription`` created a
plain SubscriptionItem at the full catalogue price — so a school shown $14.50
was invoiced $29 from the first month.

There is no code for anyone to type: activating a tier attaches a Stripe coupon
with ``duration='repeating'`` and ``duration_in_months=12``, and Stripe drops it
by itself once the year is up. That last part is Stripe's contract, not ours, so
what these tests can pin is that we ask for exactly those terms — and, more
importantly, the two ways this could quietly cost somebody money: an unscoped
coupon that discounts the institute's whole plan, and clobbering a discount the
subscription already had.
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

import stripe
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing import ai_tiers, stripe_service
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from classroom.models import School, SchoolTeacher


def _no_such_coupon():
    return stripe.error.InvalidRequestError('No such coupon', 'id')


def _catalogue():
    for slug, name, pages, price in [
        ('ai_import_starter', 'AI Question Import - Starter', 300, '29.00'),
        ('ai_import_professional', 'AI Question Import - Professional', 600, '59.00'),
        ('ai_import_enterprise', 'AI Question Import - Enterprise', 1000, '99.00'),
    ]:
        ModuleProduct.objects.update_or_create(module=slug, defaults={
            'name': name, 'pages_per_month': pages, 'price': Decimal(price),
            'is_active': True, 'stripe_price_id': f'price_{slug}',
        })


def _subscription_with(coupon_id=None):
    """A Stripe subscription object as the API would hand it back."""
    sub = MagicMock()
    if coupon_id is None:
        sub.discount = None
    else:
        sub.discount = MagicMock()
        sub.discount.coupon = MagicMock()
        sub.discount.coupon.id = coupon_id
    return sub


class CouponTermsTests(TestCase):

    def setUp(self):
        _catalogue()

    @patch('billing.stripe_service.stripe.Coupon.create')
    @patch('billing.stripe_service.stripe.Coupon.retrieve', side_effect=_no_such_coupon())
    def test_the_coupon_is_created_with_the_advertised_terms(self, retrieve, create):
        create.return_value = MagicMock(id=stripe_service.ai_intro_coupon_id())

        stripe_service.ensure_ai_intro_coupon()

        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['percent_off'], 50.0)
        # This pair is what makes Stripe charge full price from month 13 with
        # nothing of ours needing to run.
        self.assertEqual(kwargs['duration'], 'repeating')
        self.assertEqual(kwargs['duration_in_months'], 12)

    @patch('billing.stripe_service.stripe.Coupon.create')
    @patch('billing.stripe_service.stripe.Coupon.retrieve', side_effect=_no_such_coupon())
    def test_the_coupon_only_touches_the_ai_import_products(self, retrieve, create):
        """Unscoped, it would take 50% off the institute's own plan too — and
        that is not recoverable once invoiced."""
        create.return_value = MagicMock(id='c')

        stripe_service.ensure_ai_intro_coupon()

        products = create.call_args.kwargs['applies_to']['products']
        self.assertCountEqual(products, [
            'module_ai_import_starter',
            'module_ai_import_professional',
            'module_ai_import_enterprise',
        ])

    @patch('billing.stripe_service.stripe.Coupon.create')
    @patch('billing.stripe_service.stripe.Coupon.retrieve', side_effect=_no_such_coupon())
    def test_no_products_means_no_coupon_rather_than_an_unscoped_one(
        self, retrieve, create,
    ):
        ModuleProduct.objects.all().delete()

        self.assertIsNone(stripe_service.ensure_ai_intro_coupon())
        create.assert_not_called()

    @patch('billing.stripe_service.stripe.Coupon.create')
    @patch('billing.stripe_service.stripe.Coupon.retrieve')
    def test_an_existing_coupon_is_reused(self, retrieve, create):
        retrieve.return_value = MagicMock(id=stripe_service.ai_intro_coupon_id())

        coupon_id = stripe_service.ensure_ai_intro_coupon()

        self.assertEqual(coupon_id, stripe_service.ai_intro_coupon_id())
        create.assert_not_called()

    def test_the_id_carries_the_terms(self):
        """A coupon must never be reused at terms it was not created with."""
        self.assertIn('50off', stripe_service.ai_intro_coupon_id())
        self.assertIn('12m', stripe_service.ai_intro_coupon_id())

        with patch.object(ai_tiers, 'INTRO_DISCOUNT_MONTHS', 6):
            self.assertNotEqual(stripe_service.ai_intro_coupon_id(),
                                'ai-import-intro-50off-12m')


class ApplyDiscountTests(TestCase):

    def setUp(self):
        _catalogue()
        admin = CustomUser.objects.create_user('a', 'a@t.internal', 'pw1!')
        school = School.objects.create(name='S', slug='s', admin=admin)
        plan = InstitutePlan.objects.create(
            name='Basic', slug='b', price=Decimal('89.00'), class_limit=5,
            student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        self.sub = SchoolSubscription.objects.create(
            school=school, plan=plan, status='active',
            stripe_subscription_id='sub_123',
        )

    @patch('billing.stripe_service.stripe.Subscription.modify')
    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_no_stripe_subscription_is_a_no_op(self, retrieve, modify):
        """A trial school is charged nothing, so there is nothing to discount —
        and no error to show them either."""
        self.sub.stripe_subscription_id = ''

        applied, error = stripe_service.apply_ai_intro_discount(self.sub)

        self.assertFalse(applied)
        self.assertIsNone(error)
        retrieve.assert_not_called()
        modify.assert_not_called()

    @patch('billing.stripe_service.stripe.Coupon.retrieve')
    @patch('billing.stripe_service.stripe.Subscription.modify')
    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_a_clean_subscription_gets_the_discount(self, retrieve, modify, coupon):
        retrieve.return_value = _subscription_with(None)
        coupon.return_value = MagicMock(id=stripe_service.ai_intro_coupon_id())

        applied, error = stripe_service.apply_ai_intro_discount(self.sub)

        self.assertTrue(applied)
        self.assertIsNone(error)
        modify.assert_called_once_with(
            'sub_123', coupon=stripe_service.ai_intro_coupon_id(),
        )

    @patch('billing.stripe_service.stripe.Subscription.modify')
    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_a_tier_switch_does_not_restart_the_year(self, retrieve, modify):
        """Starter → Professional in month 5 still ends at month 12."""
        retrieve.return_value = _subscription_with(
            stripe_service.ai_intro_coupon_id())

        applied, error = stripe_service.apply_ai_intro_discount(self.sub)

        self.assertTrue(applied)
        self.assertIsNone(error)
        modify.assert_not_called()

    @patch('billing.stripe_service.stripe.Subscription.modify')
    @patch('billing.stripe_service.stripe.Subscription.retrieve')
    def test_an_existing_discount_is_never_overwritten(self, retrieve, modify):
        """Setting a coupon on a subscription REPLACES the one already there.

        An institute that registered on a negotiated discount code would trade
        it for this one, with nothing recording what was lost.
        """
        retrieve.return_value = _subscription_with('their-own-deal')

        applied, error = stripe_service.apply_ai_intro_discount(self.sub)

        self.assertFalse(applied)
        modify.assert_not_called()
        self.assertIn('already has a discount', error)

    @patch('billing.stripe_service.stripe.Subscription.retrieve',
           side_effect=stripe.error.APIConnectionError('down'))
    def test_a_stripe_failure_is_reported_not_swallowed(self, retrieve):
        applied, error = stripe_service.apply_ai_intro_discount(self.sub)

        self.assertFalse(applied)
        self.assertTrue(error)


class ModuleActivationTests(TestCase):
    """The click that buys a tier is the click that applies the discount."""

    def setUp(self):
        _catalogue()
        self.owner = CustomUser.objects.create_user('o', 'o@t.internal', 'pw1!')
        role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER,
            defaults={'display_name': 'Institute Owner'})
        UserRole.objects.create(user=self.owner, role=role)
        self.school = School.objects.create(
            name='S', slug='s', admin=self.owner, is_active=True)
        SchoolTeacher.objects.get_or_create(
            school=self.school, teacher=self.owner,
            defaults={'role': 'teacher', 'is_active': True})
        plan = InstitutePlan.objects.create(
            name='Basic', slug='b', price=Decimal('89.00'), class_limit=5,
            student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'))
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=plan, status='active',
            stripe_subscription_id='sub_123')
        ModuleProduct.objects.update_or_create(
            module='teachers_attendance',
            defaults={'name': 'Teachers Attendance', 'price': Decimal('10.00'),
                      'is_active': True, 'stripe_price_id': 'price_ta'})
        self.client.force_login(self.owner)

    def _activate(self, module_slug):
        return self.client.post(reverse('module_toggle'), {
            'module_slug': module_slug, 'action': 'add',
        })

    @patch('billing.stripe_service.add_module_to_subscription')
    @patch('billing.stripe_service.apply_ai_intro_discount',
           return_value=(True, None))
    def test_activating_an_ai_tier_applies_the_discount(self, apply, add):
        self._activate('ai_import_starter')

        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0].pk, self.sub.pk)

    @patch('billing.stripe_service.add_module_to_subscription')
    @patch('billing.stripe_service.apply_ai_intro_discount',
           return_value=(True, None))
    def test_a_non_ai_module_gets_no_ai_discount(self, apply, add):
        self._activate('teachers_attendance')

        apply.assert_not_called()

    @patch('billing.stripe_service.add_module_to_subscription')
    @patch('billing.stripe_service.apply_ai_intro_discount')
    def test_a_failed_discount_is_shown_to_the_person_who_clicked(
        self, apply, add,
    ):
        """They were quoted half price. Landing on full price silently is an
        overcharge nobody sees until the invoice arrives."""
        apply.return_value = (False, 'Your subscription already has a discount.')

        response = self._activate('ai_import_starter')

        shown = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn('Your subscription already has a discount.', shown)
        # ...and the activation still went through, so they get the pages they
        # are paying for. (The row itself is written by
        # add_module_to_subscription, which is mocked out here, so the view's
        # own success message is what says the flow carried on.)
        self.assertIn('AI Question Import - Starter module activated.', shown)

    @patch('billing.stripe_service.add_module_to_subscription')
    @patch('billing.stripe_service.apply_ai_intro_discount')
    def test_nothing_is_applied_while_the_offer_is_off(self, apply, add):
        with patch.object(ai_tiers, 'INTRO_DISCOUNT_ENABLED', False):
            self._activate('ai_import_starter')

        apply.assert_not_called()
