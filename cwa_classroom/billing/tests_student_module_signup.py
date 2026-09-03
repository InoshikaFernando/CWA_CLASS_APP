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
            code='FREETIER', discount_percent=100, grants_student_basic=True)
        sub = self._sub(discount_code=code)
        self.assertEqual(len(sync_student_modules(sub)), 1)
        self.assertFalse(student_can_be_ai_graded(self.user))

    def test_a_flagged_promo_code_grants_it_from_the_string_alone(self):
        """A PromoCode leaves only its code string on the subscription."""
        PromoCode.objects.create(code='PROMOFREE', discount_percent=100,
                                 grants_student_basic=True)
        sub = self._sub(promo_code_used='PROMOFREE')
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
            code='TWICE', discount_percent=100, grants_student_basic=True)
        sub = self._sub(discount_code=code)
        sync_student_modules(sub)
        sync_student_modules(sub)
        self.assertEqual(StudentModule.objects.filter(
            subscription=sub, module=StudentModule.MODULE_BASIC).count(), 1)

    def test_both_kinds_of_code_on_one_subscription_are_read(self):
        DiscountCode.objects.create(code='D-PLAIN', discount_percent=50)
        PromoCode.objects.create(code='P-FLAGGED', discount_percent=100,
                                 grants_student_basic=True)
        sub = self._sub(
            discount_code=DiscountCode.objects.get(code='D-PLAIN'),
            promo_code_used='P-FLAGGED')
        self.assertEqual(len(codes_on_subscription(sub)), 2)
        sync_student_modules(sub)
        self.assertFalse(student_can_be_ai_graded(self.user))


class PayTheRemainderByCardTests(TestCase):
    """Activation through Stripe: code entered, card charged, webhook back.

    Since Student Basic may only ride on a 100%-off code, no CODE reaches this
    path today — a free code never goes to Stripe. What is pinned here is the
    machinery, which stays right for the moment a *paid* student module exists:
    the code is recorded before the student leaves, nothing is granted until
    the payment lands, and the webhook resolves the tier off the subscription
    rather than off the form that is long gone.
    """

    def setUp(self):
        self.user = a_student('card-payer')
        self.package = a_package()
        self.code = DiscountCode.objects.create(
            code='HALFOFF', discount_percent=50, stripe_coupon_id='coup_test')

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

    def test_the_webhook_activates_them_and_resolves_the_tier(self):
        from billing.webhook_handlers import _activate_individual_from_checkout

        self.client.force_login(self.user)
        self._apply('HALFOFF')
        _activate_individual_from_checkout(
            {'user_id': str(self.user.id), 'package_id': str(self.package.id)},
            stripe_subscription_id='sub_test')

        self.user.refresh_from_db()
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        # The code survived the round trip and was read on the way back in.
        self.assertEqual(sub.discount_code, self.code)
        # It carries no tier, so they keep the app in full.
        self.assertTrue(student_can_be_ai_graded(self.user))

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

        PromoCode.objects.create(code='PARTPROMO', discount_percent=25)
        self.client.force_login(self.user)
        self._apply('PARTPROMO')
        self.assertEqual(Subscription.objects.get(
            user=self.user).promo_code_used, 'PARTPROMO')
        _activate_individual_from_checkout(
            {'user_id': str(self.user.id), 'package_id': str(self.package.id)},
            stripe_subscription_id='sub_test_3')
        self.assertTrue(student_can_be_ai_graded(self.user))


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
            code='SIGNUPBASIC', discount_percent=100,
            grants_student_basic=True)
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


class StudentBasicOnlyRidesOnAFreeCodeTests(TestCase):
    """A paying student can never be silently put on the reduced tier.

    Nothing in the sign-up flow tells them: step 3 quotes the full plan's
    price, step 5 takes the code, and there is no screen in between. So a code
    that still charges may not carry Student Basic at all. Guarded twice — in
    the model's ``clean()``, which is what the admin form runs, and again where
    the module is actually attached, which is the last point before a row
    written by a script or a fixture would do the damage.
    """

    def test_the_model_refuses_a_flagged_partial_discount_code(self):
        from django.core.exceptions import ValidationError

        code = DiscountCode(code='HALFBASIC', discount_percent=50,
                            grants_student_basic=True)
        with self.assertRaises(ValidationError) as caught:
            code.full_clean()
        self.assertIn('grants_student_basic', caught.exception.error_dict)

    def test_the_model_refuses_a_flagged_partial_promo_code(self):
        from django.core.exceptions import ValidationError

        code = PromoCode(code='HALFPROMO', discount_percent=50,
                         grants_student_basic=True)
        with self.assertRaises(ValidationError):
            code.full_clean()

    def test_a_fully_free_flagged_code_validates(self):
        DiscountCode(code='FREEBASIC2', discount_percent=100,
                     grants_student_basic=True).full_clean()

    def test_an_unflagged_partial_code_validates(self):
        DiscountCode(code='JUSTHALF', discount_percent=50,
                     stripe_coupon_id='c').full_clean()

    def test_applying_a_flagged_partial_code_is_refused_not_obeyed(self):
        """The form guard cannot see a row written by a script or a fixture."""
        from billing.entitlements import apply_code_student_modules

        user = a_student('script-victim')
        Subscription.objects.create(
            user=user, package=a_package(),
            status=Subscription.STATUS_ACTIVE)
        # Straight to the database, past full_clean() — as a fixture would.
        code = DiscountCode.objects.create(
            code='SNEAKY', discount_percent=50, grants_student_basic=True)

        with self.assertLogs('billing.entitlements', level='ERROR') as logs:
            self.assertIsNone(apply_code_student_modules(user, code))
        self.assertIn('SNEAKY', logs.output[0])
        self.assertEqual(StudentModule.objects.count(), 0)
        self.assertTrue(student_can_be_ai_graded(user))


class ThePriceQuotedIsTheRealPlanPriceTests(TestCase):
    """Never a number this page made up.

    The upgrade out of Student Basic is becoming an ordinary paying subscriber,
    so the figure has to be the one step 3 of the registration form shows. It
    is read off the ``Package``, which is the only place that price lives.
    """

    def setUp(self):
        self.user = a_student('price-reader')
        Subscription.objects.create(
            user=self.user, package=a_package(),
            status=Subscription.STATUS_ACTIVE)
        self.client.force_login(self.user)

    def test_it_quotes_the_standard_plan(self):
        from decimal import Decimal
        from billing.views import StudentAIGradingView

        Package.objects.all().delete()
        Package.objects.create(name='Wizard Monthly', price=Decimal('19.90'),
                               stripe_price_id='price_w', is_default=True)
        self.assertEqual(StudentAIGradingView.standard_plan().price,
                         Decimal('19.90'))

    def test_a_free_package_is_never_quoted_as_the_upgrade_price(self):
        """`grant_free_access` creates a $0 'Free' package. Quoting $0.00 as
        the price of the upgrade would be worse than quoting nothing."""
        from decimal import Decimal
        from billing.views import StudentAIGradingView

        Package.objects.all().delete()
        Package.objects.create(name='Free', price=Decimal('0'))
        self.assertIsNone(StudentAIGradingView.standard_plan())

    def test_the_default_package_wins_over_a_cheaper_one(self):
        from decimal import Decimal
        from billing.views import StudentAIGradingView

        Package.objects.all().delete()
        Package.objects.create(name='Cheap', price=Decimal('4.90'),
                               stripe_price_id='price_c')
        Package.objects.create(name='Wizard Monthly', price=Decimal('19.90'),
                               stripe_price_id='price_w', is_default=True)
        self.assertEqual(StudentAIGradingView.standard_plan().name,
                         'Wizard Monthly')

    def test_the_page_shows_it(self):
        from decimal import Decimal
        from billing.entitlements import grant_student_module

        Package.objects.filter(name='Individual').update(
            price=Decimal('19.90'), is_default=True)
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        response = self.client.get('/billing/ai-graded-questions/')
        self.assertContains(response, '19.90')
        self.assertContains(response, 'Student Basic')

    def test_the_page_survives_having_no_paid_package_at_all(self):
        Package.objects.all().delete()
        response = self.client.get('/billing/ai-graded-questions/')
        self.assertEqual(response.status_code, 200)


class ANewPromotionNeedsANewCodeTests(TestCase):
    """Reusing a code students already hold reaches backwards to them.

    The code is recorded on every subscription that redeemed it, and the tier
    is resolved from that code each time one of those subscriptions is
    activated. So flipping the flag on a circulating code does not only affect
    the next cohort — the next time an existing holder re-checks-out, or the
    success page runs for them, they land on Student Basic having been promised
    nothing of the sort. CWA's own free students are precisely who that would
    hit, which is why the flag freezes once a code has been redeemed.
    """

    def test_the_flag_cannot_be_flipped_on_a_redeemed_code(self):
        from django.core.exceptions import ValidationError

        code = DiscountCode.objects.create(code='CWAFREE',
                                           discount_percent=100, uses=37)
        code.grants_student_basic = True
        with self.assertRaises(ValidationError) as caught:
            code.full_clean()
        message = str(caught.exception)
        self.assertIn('already been redeemed', message)
        self.assertIn('Issue a new code', message)

    def test_the_same_holds_for_a_promo_code(self):
        from django.core.exceptions import ValidationError

        code = PromoCode.objects.create(code='OLDPROMO',
                                        discount_percent=100, uses=5)
        code.grants_student_basic = True
        with self.assertRaises(ValidationError):
            code.full_clean()

    def test_it_cannot_be_turned_off_on_a_redeemed_code_either(self):
        """Symmetrical: the students on it were promised the reduced tier and
        the price that went with it, and un-flagging changes that too."""
        from django.core.exceptions import ValidationError

        code = DiscountCode.objects.create(
            code='PROMO26', discount_percent=100,
            grants_student_basic=True, uses=12)
        code.grants_student_basic = False
        with self.assertRaises(ValidationError):
            code.full_clean()

    def test_an_unredeemed_code_can_still_be_corrected(self):
        """A typo on a code nobody has used yet is just a typo."""
        code = DiscountCode.objects.create(code='NOTYETUSED',
                                           discount_percent=100)
        code.grants_student_basic = True
        code.full_clean()

    def test_a_brand_new_code_is_the_supported_route(self):
        """What the error tells the owner to do, working end to end."""
        old = DiscountCode.objects.create(code='CWAFREE2',
                                          discount_percent=100, uses=37)
        new = DiscountCode.objects.create(
            code='PROMO2026', discount_percent=100, grants_student_basic=True)
        new.full_clean()

        existing = a_student('existing-cwa')
        Subscription.objects.create(
            user=existing, package=a_package(),
            status=Subscription.STATUS_ACTIVE, discount_code=old)
        promo = a_student('promo-cohort')
        promo_sub = Subscription.objects.create(
            user=promo, package=a_package(),
            status=Subscription.STATUS_ACTIVE, discount_code=new)

        sync_student_modules(Subscription.objects.get(user=existing))
        sync_student_modules(promo_sub)

        self.assertTrue(student_can_be_ai_graded(existing))
        self.assertFalse(student_can_be_ai_graded(promo))

    def test_editing_something_else_on_a_redeemed_code_still_works(self):
        """The freeze is on the flag, not on the whole row."""
        code = DiscountCode.objects.create(code='STILLEDITABLE',
                                           discount_percent=100, uses=9)
        code.max_uses = 100
        code.full_clean()
        code.save(update_fields=['max_uses'])
        self.assertEqual(
            DiscountCode.objects.get(pk=code.pk).max_uses, 100)
