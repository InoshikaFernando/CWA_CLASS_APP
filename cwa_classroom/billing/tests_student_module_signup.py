"""Every way a student can subscribe with a promotion code ends on the same tier.

There are two shapes of promotion and they activate at completely different
moments:

* a code that covers the price **in full** activates the student on the spot,
  before Stripe is ever involved;
* a code that leaves a **balance to pay** sends them to Stripe and the
  subscription is activated minutes later by the webhook — or, if that is lost,
  by the success page.

Granting the module when the code was TYPED would have worked only for the
first kind. A half-price promotion would have quietly handed out the AI-graded
questions it was sold without, and nothing would have failed loudly. So the code
is recorded on the subscription and the tier is resolved from it every time the
subscription becomes real (``sync_student_modules``).

These pin that: same code, same tier, whichever route the student took, and
no tier at all for the ordinary codes that carry no flag.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.entitlements import (
    codes_on_subscription, sync_student_modules,
)
from billing.models import (
    DiscountCode, Package, PromoCode, StudentModule, Subscription,
)
from worksheets.grading_service import student_can_be_ai_graded

User = get_user_model()


def a_student(username):
    return User.objects.create_user(
        username=username, password='pass1234', email=f'{username}@test.com')


def a_package():
    package, _ = Package.objects.get_or_create(
        name='Individual', defaults={'price': 19.90, 'class_limit': 0,
                                     'stripe_price_id': 'price_test'})
    return package


class SyncReadsTheCodeOffTheSubscriptionTests(TestCase):
    def setUp(self):
        self.user = a_student('sync-me')
        self.package = a_package()

    def _sub(self, **kwargs):
        return Subscription.objects.create(
            user=self.user, package=self.package,
            status=Subscription.STATUS_ACTIVE, **kwargs)

    def test_a_flagged_discount_code_grants_the_tier(self):
        code = DiscountCode.objects.create(
            code='HALFPRICE', discount_percent=50, grants_student_basic=True)
        sub = self._sub(discount_code=code)
        self.assertEqual(len(sync_student_modules(sub)), 1)
        self.assertFalse(student_can_be_ai_graded(self.user))

    def test_a_flagged_promo_code_grants_it_from_the_string_alone(self):
        """A PromoCode leaves only its code string on the subscription."""
        PromoCode.objects.create(code='PROMOHALF', discount_percent=50,
                                 grants_student_basic=True)
        sub = self._sub(promo_code_used='PROMOHALF')
        self.assertEqual(len(sync_student_modules(sub)), 1)
        self.assertFalse(student_can_be_ai_graded(self.user))

    def test_an_unflagged_code_grants_nothing(self):
        code = DiscountCode.objects.create(code='PLAIN', discount_percent=50)
        sub = self._sub(discount_code=code)
        self.assertEqual(sync_student_modules(sub), [])
        self.assertTrue(student_can_be_ai_graded(self.user))

    def test_no_code_at_all_grants_nothing(self):
        self.assertEqual(sync_student_modules(self._sub()), [])
        self.assertTrue(student_can_be_ai_graded(self.user))

    def test_a_code_string_that_matches_nothing_is_survived(self):
        """A code deleted after redemption must not 500 an activation."""
        sub = self._sub(promo_code_used='DELETED-LONG-AGO')
        self.assertEqual(sync_student_modules(sub), [])

    def test_syncing_twice_leaves_one_row(self):
        """The webhook and the success page both sync the same subscription."""
        code = DiscountCode.objects.create(
            code='TWICE', discount_percent=50, grants_student_basic=True)
        sub = self._sub(discount_code=code)
        sync_student_modules(sub)
        sync_student_modules(sub)
        self.assertEqual(StudentModule.objects.filter(
            subscription=sub, module=StudentModule.MODULE_BASIC).count(), 1)

    def test_both_kinds_of_code_on_one_subscription_are_read(self):
        DiscountCode.objects.create(code='D-PLAIN', discount_percent=50)
        PromoCode.objects.create(code='P-FLAGGED', discount_percent=50,
                                 grants_student_basic=True)
        sub = self._sub(
            discount_code=DiscountCode.objects.get(code='D-PLAIN'),
            promo_code_used='P-FLAGGED')
        self.assertEqual(len(codes_on_subscription(sub)), 2)
        sync_student_modules(sub)
        self.assertFalse(student_can_be_ai_graded(self.user))


class PayTheRemainderByCardTests(TestCase):
    """The path the money actually takes: code entered, card charged, webhook.

    The student leaves for Stripe with nothing granted, and comes back
    activated by ``_activate_individual_from_checkout``. What the code says has
    to survive that round trip.
    """

    def setUp(self):
        self.user = a_student('card-payer')
        self.package = a_package()
        self.code = DiscountCode.objects.create(
            code='HALFOFF', discount_percent=50, grants_student_basic=True,
            stripe_coupon_id='coup_test')

    def _apply(self, code):
        """POST the code the way the page does — a JSON body, not a form."""
        return self.client.post(
            f'/billing/apply-promo/{self.package.id}/',
            data=json.dumps({'code': code}),
            content_type='application/json')

    def test_the_code_is_recorded_before_the_student_leaves_for_stripe(self):
        """``ApplyPromoCodeView``'s partial branch. Nothing was stored before
        this, so there was nothing for the webhook to read on the way back."""
        self.client.force_login(self.user)
        response = self._apply('HALFOFF')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['fully_free'])
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.discount_code, self.code)

    def test_nothing_is_granted_until_the_payment_lands(self):
        self.client.force_login(self.user)
        self._apply('HALFOFF')
        self.assertEqual(StudentModule.objects.count(), 0)

    def test_the_webhook_activation_puts_them_on_the_tier(self):
        from billing.webhook_handlers import _activate_individual_from_checkout

        self.client.force_login(self.user)
        self._apply('HALFOFF')
        _activate_individual_from_checkout(
            {'user_id': str(self.user.id), 'package_id': str(self.package.id)},
            stripe_subscription_id='sub_test')

        self.user.refresh_from_db()
        self.assertFalse(student_can_be_ai_graded(self.user))
        self.assertEqual(Subscription.objects.get(user=self.user).status,
                         Subscription.STATUS_ACTIVE)

    def test_an_unflagged_half_price_code_leaves_them_on_the_full_app(self):
        from billing.webhook_handlers import _activate_individual_from_checkout

        DiscountCode.objects.create(code='JUSTCHEAP', discount_percent=50,
                                    stripe_coupon_id='coup_2')
        self.client.force_login(self.user)
        self._apply('JUSTCHEAP')
        _activate_individual_from_checkout(
            {'user_id': str(self.user.id), 'package_id': str(self.package.id)},
            stripe_subscription_id='sub_test_2')
        self.assertTrue(student_can_be_ai_graded(self.user))

    def test_a_promo_code_takes_the_same_route(self):
        from billing.webhook_handlers import _activate_individual_from_checkout

        PromoCode.objects.create(code='PARTPROMO', discount_percent=25,
                                 grants_student_basic=True)
        self.client.force_login(self.user)
        self._apply('PARTPROMO')
        self.assertEqual(Subscription.objects.get(
            user=self.user).promo_code_used, 'PARTPROMO')
        _activate_individual_from_checkout(
            {'user_id': str(self.user.id), 'package_id': str(self.package.id)},
            stripe_subscription_id='sub_test_3')
        self.assertFalse(student_can_be_ai_graded(self.user))


class FullyFreeCodeTests(TestCase):
    """The other shape: no card, activated on the spot."""

    def setUp(self):
        self.user = a_student('free-rider')
        self.package = a_package()

    def _apply(self, code):
        """POST the code the way the page does — a JSON body, not a form."""
        return self.client.post(
            f'/billing/apply-promo/{self.package.id}/',
            data=json.dumps({'code': code}),
            content_type='application/json')

    def test_a_flagged_free_discount_code_grants_the_tier_immediately(self):
        DiscountCode.objects.create(code='FREEBASIC', discount_percent=100,
                                    grants_student_basic=True)
        self.client.force_login(self.user)
        response = self._apply('FREEBASIC')
        self.assertTrue(response.json()['fully_free'])
        self.assertFalse(student_can_be_ai_graded(self.user))

    def test_the_code_is_recorded_on_the_subscription(self):
        code = DiscountCode.objects.create(
            code='FREEREC', discount_percent=100, grants_student_basic=True)
        self.client.force_login(self.user)
        self._apply('FREEREC')
        self.assertEqual(
            Subscription.objects.get(user=self.user).discount_code, code)

    def test_an_ordinary_free_code_still_grants_the_app_in_full(self):
        DiscountCode.objects.create(code='JUSTFREE', discount_percent=100)
        self.client.force_login(self.user)
        self._apply('JUSTFREE')
        self.assertTrue(student_can_be_ai_graded(self.user))

    def test_a_flagged_free_promo_code_grants_the_tier(self):
        PromoCode.objects.create(code='FREEPROMO', discount_percent=100,
                                 grants_student_basic=True)
        self.client.force_login(self.user)
        response = self._apply('FREEPROMO')
        self.assertTrue(response.json()['fully_free'])
        self.assertFalse(student_can_be_ai_graded(self.user))


class SignUpAndPayThenGetAnAccountTests(TestCase):
    """An individual signing up from scratch on a paid package.

    They have no account while they pay, so the code rides in the
    ``PendingRegistration`` and has to reach the subscription created for them
    afterwards.
    """

    def test_the_code_reaches_the_subscription_it_created(self):
        from accounts.models import PendingRegistration
        from billing.views import _create_account_from_pending
        from django.contrib.auth.hashers import make_password

        package = a_package()
        code = DiscountCode.objects.create(
            code='SIGNUPBASIC', discount_percent=50,
            grants_student_basic=True, stripe_coupon_id='coup_s')
        pending = PendingRegistration.objects.create(
            stripe_session_id='cs_test_1', email='newbie@test.com',
            username='newbie', password_hash=make_password('pass1234'),
            package_id=package.id,
            data={'first_name': 'New', 'last_name': 'Bie',
                  'discount_code': 'SIGNUPBASIC'})

        user = _create_account_from_pending(pending,
                                            stripe_subscription_id='sub_np')
        self.assertIsNotNone(user)
        self.assertEqual(Subscription.objects.get(user=user).discount_code,
                         code)
        self.assertFalse(student_can_be_ai_graded(user))

    def test_signing_up_without_a_code_grants_the_app_in_full(self):
        from accounts.models import PendingRegistration
        from billing.views import _create_account_from_pending
        from django.contrib.auth.hashers import make_password

        package = a_package()
        pending = PendingRegistration.objects.create(
            stripe_session_id='cs_test_2', email='plain@test.com',
            username='plainpayer', password_hash=make_password('pass1234'),
            package_id=package.id, data={'discount_code': None})

        user = _create_account_from_pending(pending)
        self.assertTrue(student_can_be_ai_graded(user))
        self.assertEqual(StudentModule.objects.count(), 0)
