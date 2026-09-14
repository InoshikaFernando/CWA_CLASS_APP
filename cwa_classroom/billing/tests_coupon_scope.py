"""Scoping a discount to the products it was meant for.

EARLYBIRD in production is 50% off, `applies_to=None`, `duration=forever`. On a
school holding $315/mo that is $157.50 a month, and it grows with every module
they add — an open-ended commitment nobody chose, made by a coupon builder that
never set a scope.

Unscoped is not just expensive, it is exclusive. Two subscription discounts
reaching the same line compound — two 50% coupons take 75% off, not 50% — so
an unscoped coupon makes every other offer unaddable. That is why a school on
an institute discount code could never receive the AI import introductory
price the plans page promises them.

These cover the two halves: building a coupon at a scope, and adding a second
discount beside one without the two ever touching the same line.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import stripe
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from billing import stripe_service
from billing.models import DiscountCode, InstitutePlan


def _price_to_product(price_id, **kwargs):
    return {'id': price_id, 'product': f'prod_for_{price_id}'}


def _plans():
    for slug, price, pid in [('basic', '89.00', 'price_basic'),
                             ('platinum', '189.00', 'price_platinum')]:
        InstitutePlan.objects.create(
            name=slug.title(), slug=slug, price=Decimal(price),
            stripe_price_id=pid, class_limit=5, student_limit=100,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )


PLAN_PRODUCTS = ['prod_for_price_basic', 'prod_for_price_platinum']


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class CouponScopeTests(TestCase):

    def setUp(self):
        _plans()
        p = patch('billing.stripe_service.stripe.Price.retrieve',
                  side_effect=_price_to_product)
        p.start()
        self.addCleanup(p.stop)

    def test_an_unscoped_code_builds_an_unscoped_coupon(self):
        """The legacy default, kept so existing codes do not change meaning."""
        code = DiscountCode(code='LEGACY', discount_percent=50,
                            scope=DiscountCode.SCOPE_EVERYTHING)
        self.assertNotIn('applies_to', stripe_service._build_stripe_coupon_kwargs(code))

    def test_a_plan_scoped_code_names_the_plan_products(self):
        code = DiscountCode(code='EARLYBIRD', discount_percent=50,
                            scope=DiscountCode.SCOPE_PLANS)
        kwargs = stripe_service._build_stripe_coupon_kwargs(code)
        self.assertCountEqual(kwargs['applies_to']['products'], PLAN_PRODUCTS)

    def test_a_scope_with_no_products_refuses_rather_than_widening(self):
        """Falling back to unscoped would turn "half off the plan" into "half
        off everything they ever buy" — the exact failure this prevents."""
        InstitutePlan.objects.all().delete()
        code = DiscountCode(code='EARLYBIRD', discount_percent=50,
                            scope=DiscountCode.SCOPE_PLANS)
        with self.assertRaises(ValueError):
            stripe_service._build_stripe_coupon_kwargs(code)


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class AddSubscriptionDiscountTests(TestCase):
    """Stripe does not police overlap; this does."""

    def _sub(self, *coupons):
        return {'discounts': [{'coupon': c} for c in coupons]}

    def test_a_first_discount_is_added(self):
        with patch('stripe.Subscription.retrieve', return_value=self._sub()), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'ai-intro', {'prod_ai'})
        self.assertTrue(added)
        self.assertIsNone(error)
        self.assertEqual(modify.call_args.kwargs['discounts'],
                         [{'coupon': 'ai-intro'}])

    def test_a_disjoint_discount_sits_beside_the_existing_one(self):
        existing = {'id': 'earlybird', 'applies_to': {'products': ['prod_plan']}}
        with patch('stripe.Subscription.retrieve', return_value=self._sub(existing)), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'ai-intro', {'prod_ai'})
        self.assertTrue(added)
        self.assertEqual(modify.call_args.kwargs['discounts'],
                         [{'coupon': 'earlybird'}, {'coupon': 'ai-intro'}])

    def test_the_existing_discount_is_kept_not_replaced(self):
        """Replacing would trade a negotiated deal for this one, with nothing
        recording what was lost."""
        existing = {'id': 'their-deal', 'applies_to': {'products': ['prod_plan']}}
        with patch('stripe.Subscription.retrieve', return_value=self._sub(existing)), \
             patch('stripe.Subscription.modify') as modify:
            stripe_service.add_subscription_discount('sub_1', 'ai-intro', {'prod_ai'})
        self.assertIn({'coupon': 'their-deal'},
                      modify.call_args.kwargs['discounts'])

    def test_an_overlapping_discount_is_refused(self):
        existing = {'id': 'other-ai', 'applies_to': {'products': ['prod_ai']}}
        with patch('stripe.Subscription.retrieve', return_value=self._sub(existing)), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'ai-intro', {'prod_ai'})
        self.assertFalse(added)
        modify.assert_not_called()
        self.assertIn('twice', error)

    def test_an_unscoped_existing_discount_blocks_and_names_the_remedy(self):
        """The production case. The message has to say "scope it" or nobody
        reading it knows what to do next."""
        existing = {'id': 'EARLYBIRD'}
        with patch('stripe.Subscription.retrieve', return_value=self._sub(existing)), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'ai-intro', {'prod_ai'})
        self.assertFalse(added)
        modify.assert_not_called()
        self.assertIn('EARLYBIRD', error)
        self.assertIn('scope', error.lower())

    def test_an_unscoped_new_coupon_is_refused_beside_a_scoped_one(self):
        existing = {'id': 'ai-intro', 'applies_to': {'products': ['prod_ai']}}
        with patch('stripe.Subscription.retrieve', return_value=self._sub(existing)), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'blanket', None)
        self.assertFalse(added)
        modify.assert_not_called()

    def test_adding_the_same_coupon_twice_is_a_no_op(self):
        """Adding it again would stack it on itself."""
        existing = {'id': 'ai-intro', 'applies_to': {'products': ['prod_ai']}}
        with patch('stripe.Subscription.retrieve', return_value=self._sub(existing)), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'ai-intro', {'prod_ai'})
        self.assertTrue(added)
        modify.assert_not_called()

    def test_a_legacy_single_discount_field_is_still_read(self):
        """Older API versions return `discount`, not `discounts`. Missing it
        would read as "no discounts" and stack on top of a live one."""
        sub = {'discount': {'coupon': {'id': 'EARLYBIRD'}}}
        with patch('stripe.Subscription.retrieve', return_value=sub), \
             patch('stripe.Subscription.modify') as modify:
            added, error = stripe_service.add_subscription_discount(
                'sub_1', 'ai-intro', {'prod_ai'})
        self.assertFalse(added)
        modify.assert_not_called()


@override_settings(STRIPE_SECRET_KEY='sk_test_fake')
class RescopeCommandTests(TestCase):

    def setUp(self):
        _plans()
        self.code = DiscountCode.objects.create(
            code='EARLYBIRD', discount_percent=50,
            stripe_coupon_id='xhHrssT8', scope=DiscountCode.SCOPE_PLANS,
        )
        p = patch('billing.stripe_service.stripe.Price.retrieve',
                  side_effect=_price_to_product)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command('rescope_discount_code', 'EARLYBIRD', *args,
                     stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_an_unknown_code_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command('rescope_discount_code', 'NOPE', stdout=StringIO())

    def test_dry_run_creates_nothing(self):
        with patch('stripe.Coupon.retrieve', return_value={'id': 'xhHrssT8'}), \
             patch('stripe.Coupon.create') as create:
            out = self._run()
        create.assert_not_called()
        self.code.refresh_from_db()
        self.assertEqual(self.code.stripe_coupon_id, 'xhHrssT8')
        self.assertIn('DRY RUN', out)

    def test_dry_run_names_the_current_unscoped_reach(self):
        with patch('stripe.Coupon.retrieve', return_value={'id': 'xhHrssT8'}), \
             patch('stripe.Coupon.create'):
            out = self._run()
        self.assertIn('EVERYTHING', out)

    def test_apply_mints_a_scoped_coupon_and_repoints_the_code(self):
        with patch('stripe.Coupon.retrieve', return_value={'id': 'xhHrssT8'}), \
             patch('stripe.Coupon.create', return_value={'id': 'earlybird-plans'}) as create:
            self._run('--apply')
        self.assertCountEqual(
            create.call_args.kwargs['applies_to']['products'], PLAN_PRODUCTS)
        self.code.refresh_from_db()
        self.assertEqual(self.code.stripe_coupon_id, 'earlybird-plans')

    def test_a_coupon_already_at_the_right_scope_is_left_alone(self):
        existing = {'id': 'xhHrssT8',
                    'applies_to': {'products': PLAN_PRODUCTS}}
        with patch('stripe.Coupon.retrieve', return_value=existing), \
             patch('stripe.Coupon.create') as create:
            out = self._run('--apply')
        create.assert_not_called()
        self.assertIn('nothing to do', out)
