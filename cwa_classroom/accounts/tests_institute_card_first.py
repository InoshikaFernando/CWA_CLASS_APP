"""Institute signup: card first, 14-day trial, cancel free, then charged.

The old flow created the user, the school and a trialing SchoolSubscription and
*then* redirected to Stripe. Closing that tab left a fully working school with
no card on file, and nothing noticed until the trial expired a fortnight later.

The contract now, one test class per step:

1. Nothing is created until Stripe confirms the card.
2. Stripe is asked for a card, and for a 14-day trial.
3. Abandoning checkout leaves no trace.
4. Completing checkout builds the account, trialing, with Stripe's own dates.
5. Building it twice makes one school, not two.
6. Cancelling inside the trial costs nothing.
7. When the trial ends, the first payment lands and the school goes active.
8. A fully-free code still needs no card.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.hashers import check_password
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    CustomUser, PendingInstituteRegistration, Role, UserRole,
)
from billing.models import InstituteDiscountCode, InstitutePlan, SchoolSubscription
from classroom.models import School

CHECKOUT_URL = 'https://checkout.stripe.com/c/pay/cs_test_inst'
SESSION_ID = 'cs_test_inst_123'
SUB_ID = 'sub_test_inst_123'
CUSTOMER_ID = 'cus_test_inst_123'


def a_plan(**kw):
    defaults = dict(
        name='Basic', slug='basic-card', price=89,
        stripe_price_id='price_basic_card', class_limit=5, student_limit=100,
        invoice_limit_yearly=500, extra_invoice_rate=0.30, trial_days=14,
        is_active=True, order=1,
    )
    defaults.update(kw)
    return InstitutePlan.objects.create(**defaults)


def form(**kw):
    data = {
        'username': 'newhoi', 'email': 'newhoi@example.com',
        'password': 'securepass1', 'confirm_password': 'securepass1',
        'center_name': 'Bright Minds Academy', 'accept_terms': 'on',
        'abn': '123', 'phone': '555', 'street_address': '1 Main St',
        'city': 'Auckland', 'state_region': 'AKL', 'postal_code': '1010',
        'country': 'NZ',
    }
    data.update(kw)
    return data


def stripe_session(**kw):
    session = MagicMock()
    session.id = kw.get('id', SESSION_ID)
    session.url = kw.get('url', CHECKOUT_URL)
    return session


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step1_NothingExistsBeforeTheCard(TestCase):
    """The regression this whole change exists for."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')
        self.plan = a_plan()

    @patch('billing.stripe_service.create_pending_institute_checkout_session')
    def test_no_user_school_or_subscription_is_created(self, mock_session):
        mock_session.return_value = stripe_session()
        resp = self.client.post(self.url, form(plan_id=self.plan.id))

        self.assertEqual(resp.status_code, 302)
        self.assertIn('checkout.stripe.com', resp.url)
        self.assertFalse(CustomUser.objects.filter(username='newhoi').exists())
        self.assertFalse(School.objects.filter(name='Bright Minds Academy').exists())
        self.assertEqual(SchoolSubscription.objects.count(), 0)

    @patch('billing.stripe_service.create_pending_institute_checkout_session')
    def test_the_details_are_held_pending_not_discarded(self, mock_session):
        mock_session.return_value = stripe_session()
        self.client.post(self.url, form(plan_id=self.plan.id))

        pending = PendingInstituteRegistration.objects.get(
            stripe_session_id=SESSION_ID)
        self.assertEqual(pending.username, 'newhoi')
        self.assertEqual(pending.center_name, 'Bright Minds Academy')
        self.assertEqual(pending.plan_id, self.plan.id)
        self.assertEqual(pending.data['city'], 'Auckland')
        self.assertFalse(pending.completed)

    @patch('billing.stripe_service.create_pending_institute_checkout_session')
    def test_the_password_is_stored_hashed_never_in_clear(self, mock_session):
        mock_session.return_value = stripe_session()
        self.client.post(self.url, form(plan_id=self.plan.id))

        pending = PendingInstituteRegistration.objects.get(
            stripe_session_id=SESSION_ID)
        self.assertNotEqual(pending.password_hash, 'securepass1')
        self.assertTrue(check_password('securepass1', pending.password_hash))

    @patch('billing.stripe_service.create_pending_institute_checkout_session',
           side_effect=Exception('Stripe is down'))
    def test_a_stripe_failure_creates_nothing_and_says_so(self, _mock):
        resp = self.client.post(self.url, form(plan_id=self.plan.id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No account was created')
        self.assertContains(resp, 'have not been charged')
        self.assertFalse(CustomUser.objects.filter(username='newhoi').exists())
        self.assertEqual(PendingInstituteRegistration.objects.count(), 0)

    def test_validation_still_runs_before_stripe_is_touched(self):
        resp = self.client.post(self.url, form(plan_id=self.plan.id,
                                               confirm_password='different'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PendingInstituteRegistration.objects.count(), 0)


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step2_StripeIsAskedForACardAndATrial(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')
        self.plan = a_plan()

    @patch('stripe.checkout.Session.create')
    def test_card_is_collected_and_the_trial_is_fourteen_days(self, mock_create):
        mock_create.return_value = stripe_session()
        self.client.post(self.url, form(plan_id=self.plan.id))

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['mode'], 'subscription')
        self.assertEqual(kwargs['payment_method_types'], ['card'])
        # Explicit, not left to a Stripe default that has moved before.
        self.assertEqual(kwargs['payment_method_collection'], 'always')
        self.assertEqual(kwargs['subscription_data']['trial_period_days'], 14)

    @patch('stripe.checkout.Session.create')
    def test_the_plan_price_is_what_is_charged(self, mock_create):
        mock_create.return_value = stripe_session()
        self.client.post(self.url, form(plan_id=self.plan.id))
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['line_items'],
                         [{'price': 'price_basic_card', 'quantity': 1}])

    @patch('stripe.checkout.Session.create')
    def test_a_plans_own_trial_length_is_honoured(self, mock_create):
        mock_create.return_value = stripe_session()
        plan = a_plan(name='Gold', slug='gold-card', trial_days=30,
                      stripe_price_id='price_gold_card', order=2)
        self.client.post(self.url, form(plan_id=plan.id, username='goldhoi',
                                        email='gold@example.com'))
        self.assertEqual(
            mock_create.call_args.kwargs['subscription_data']['trial_period_days'], 30)

    @patch('stripe.checkout.Session.create')
    def test_a_partial_discount_rides_along_as_a_coupon(self, mock_create):
        mock_create.return_value = stripe_session()
        InstituteDiscountCode.objects.create(
            code='HALFOFF', discount_percent=50, is_active=True,
            stripe_coupon_id='coupon_half',
        )
        self.client.post(self.url, form(plan_id=self.plan.id,
                                        discount_code='HALFOFF'))
        self.assertEqual(mock_create.call_args.kwargs['discounts'],
                         [{'coupon': 'coupon_half'}])


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step3_AbandoningCheckoutLeavesNothing(TestCase):

    def setUp(self):
        self.client = Client()
        self.plan = a_plan()

    @patch('billing.stripe_service.create_pending_institute_checkout_session')
    def test_walking_away_leaves_no_usable_account(self, mock_session):
        """The old flow's actual bug: a working school with no card."""
        mock_session.return_value = stripe_session()
        self.client.post(reverse('register_teacher_center'),
                         form(plan_id=self.plan.id))

        # The person closes the tab. Nothing further happens.
        self.assertFalse(CustomUser.objects.filter(username='newhoi').exists())
        self.assertEqual(School.objects.count(), 0)
        self.assertEqual(SchoolSubscription.objects.count(), 0)

        # And they cannot log in with the details they typed.
        self.assertFalse(self.client.login(username='newhoi',
                                           password='securepass1'))


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step4_CompletingCheckoutBuildsTheInstitute(TestCase):

    def setUp(self):
        self.plan = a_plan()
        self.trial_end = timezone.now() + timedelta(days=14)
        self.pending = PendingInstituteRegistration.objects.create(
            stripe_session_id=SESSION_ID,
            email='newhoi@example.com', username='newhoi',
            password_hash='pbkdf2_sha256$dummy',
            center_name='Bright Minds Academy', plan_id=self.plan.id,
            data={'city': 'Auckland', 'phone': '555', 'country': 'NZ'},
        )

    def _activate(self):
        from accounts.institute_registration import activate_pending_institute
        return activate_pending_institute(
            self.pending, stripe_subscription_id=SUB_ID,
            stripe_customer_id=CUSTOMER_ID, trial_end=self.trial_end,
        )

    @patch('stripe.Subscription.modify')
    def test_user_school_and_subscription_all_appear(self, _mock):
        user, school, sub = self._activate()
        self.assertEqual(user.username, 'newhoi')
        self.assertEqual(school.name, 'Bright Minds Academy')
        self.assertEqual(school.admin, user)
        self.assertEqual(school.city, 'Auckland')
        self.assertEqual(sub.school, school)

    @patch('stripe.Subscription.modify')
    def test_the_user_is_head_of_institute(self, _mock):
        user, _, _ = self._activate()
        self.assertTrue(user.has_role(Role.HEAD_OF_INSTITUTE))

    @patch('stripe.Subscription.modify')
    def test_the_subscription_is_trialing_not_active(self, _mock):
        """They have not paid yet — 'active' would misreport revenue."""
        _, _, sub = self._activate()
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)

    @patch('stripe.Subscription.modify')
    def test_stripes_own_trial_end_is_stored(self, _mock):
        """Not a locally computed +14 days, which would drift from Stripe."""
        _, _, sub = self._activate()
        self.assertEqual(sub.trial_end, self.trial_end)

    @patch('stripe.Subscription.modify')
    def test_the_stripe_ids_are_recorded(self, _mock):
        _, _, sub = self._activate()
        self.assertEqual(sub.stripe_subscription_id, SUB_ID)
        self.assertEqual(sub.stripe_customer_id, CUSTOMER_ID)

    @patch('stripe.Subscription.modify')
    def test_the_trial_is_marked_spent(self, _mock):
        """Otherwise cancel-and-re-register renews the trial forever."""
        _, _, sub = self._activate()
        self.assertTrue(sub.has_used_trial)

    @patch('stripe.Subscription.modify')
    def test_the_pending_row_is_closed(self, _mock):
        self._activate()
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.completed)

    @patch('stripe.Subscription.modify')
    def test_stripe_is_told_which_school_this_is(self, mock_modify):
        """So later status changes route by metadata, not a fallback lookup."""
        _, school, _ = self._activate()
        kwargs = mock_modify.call_args.kwargs
        self.assertEqual(kwargs['metadata']['school_id'], school.id)
        self.assertEqual(kwargs['metadata']['type'], 'institute')

    @patch('stripe.Subscription.modify', side_effect=Exception('Stripe down'))
    def test_a_failure_tagging_stripe_does_not_lose_the_account(self, _mock):
        user, school, sub = self._activate()
        self.assertIsNotNone(user)
        self.assertIsNotNone(school)
        self.assertEqual(sub.status, SchoolSubscription.STATUS_TRIALING)

    @patch('stripe.Subscription.modify')
    def test_a_deactivated_plan_is_refused_rather_than_half_built(self, _mock):
        InstitutePlan.objects.filter(id=self.plan.id).delete()
        user, school, sub = self._activate()
        self.assertIsNone(user)
        self.assertIsNone(school)
        self.assertEqual(School.objects.count(), 0)


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step5_BuildingItTwiceMakesOneSchool(TestCase):
    """The webhook and the browser redirect routinely arrive together."""

    def setUp(self):
        self.plan = a_plan()
        self.pending = PendingInstituteRegistration.objects.create(
            stripe_session_id=SESSION_ID,
            email='newhoi@example.com', username='newhoi',
            password_hash='pbkdf2_sha256$dummy',
            center_name='Bright Minds Academy', plan_id=self.plan.id,
            data={},
        )

    @patch('stripe.Subscription.modify')
    def test_two_activations_produce_one_school_and_one_user(self, _mock):
        from accounts.institute_registration import activate_pending_institute
        trial_end = timezone.now() + timedelta(days=14)

        first_user, first_school, _ = activate_pending_institute(
            self.pending, stripe_subscription_id=SUB_ID, trial_end=trial_end)
        second_user, second_school, _ = activate_pending_institute(
            self.pending, stripe_subscription_id=SUB_ID, trial_end=trial_end)

        self.assertEqual(CustomUser.objects.filter(username='newhoi').count(), 1)
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(SchoolSubscription.objects.count(), 1)
        self.assertEqual(first_user.pk, second_user.pk)
        self.assertEqual(first_school.pk, second_school.pk)

    @patch('stripe.Subscription.modify')
    def test_the_webhook_builds_it_from_a_session_id(self, _mock):
        from billing.webhook_handlers import handle_checkout_completed
        with patch('billing.webhook_handlers._stripe_trial_end',
                   return_value=timezone.now() + timedelta(days=14)):
            handle_checkout_completed({'object': {
                'id': SESSION_ID,
                'metadata': {'type': 'pending_institute_registration'},
                'subscription': SUB_ID,
                'customer': CUSTOMER_ID,
            }})
        school = School.objects.get(name='Bright Minds Academy')
        self.assertEqual(school.subscription.status,
                         SchoolSubscription.STATUS_TRIALING)
        self.assertEqual(school.subscription.stripe_customer_id, CUSTOMER_ID)

    def test_an_unknown_session_is_logged_not_crashed(self):
        from billing.webhook_handlers import handle_checkout_completed
        handle_checkout_completed({'object': {
            'id': 'cs_never_seen',
            'metadata': {'type': 'pending_institute_registration'},
            'subscription': SUB_ID, 'customer': CUSTOMER_ID,
        }})
        self.assertEqual(School.objects.count(), 0)


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step6_CancellingInsideTheTrialCostsNothing(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            'hoi', 'hoi@example.com', 'pass1234')
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'})
        UserRole.objects.create(user=self.user, role=role)
        self.school = School.objects.create(
            name='Bright Minds', slug='bright-cancel', admin=self.user)
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=a_plan(),
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end=timezone.now() + timedelta(days=7),
            has_used_trial=True,
            stripe_subscription_id=SUB_ID,
            invoice_year_start=timezone.now().date(),
        )
        self.client.force_login(self.user)

    @patch('stripe.Subscription.modify')
    def test_cancelling_stops_the_first_charge_at_the_trial_end(self, mock_modify):
        """cancel_at_period_end during a trial means Stripe never invoices."""
        resp = self.client.post(reverse('institute_cancel_subscription'))
        self.assertEqual(resp.status_code, 302)
        mock_modify.assert_called_once()
        self.assertEqual(mock_modify.call_args.args[0], SUB_ID)
        self.assertTrue(mock_modify.call_args.kwargs['cancel_at_period_end'])

    @patch('stripe.Subscription.modify')
    def test_access_continues_until_the_trial_ends(self, _mock):
        """Cancelling is not the same as leaving immediately."""
        self.client.post(reverse('institute_cancel_subscription'))
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SchoolSubscription.STATUS_TRIALING)
        self.assertGreater(self.sub.trial_end, timezone.now())

    def test_cancelling_without_a_stripe_subscription_is_refused_clearly(self):
        SchoolSubscription.objects.filter(pk=self.sub.pk).update(
            stripe_subscription_id='')
        resp = self.client.post(reverse('institute_cancel_subscription'),
                                follow=True)
        self.assertContains(resp, 'No active subscription to cancel')


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step7_AfterTheTrialTheFirstPaymentLands(TestCase):

    def setUp(self):
        user = CustomUser.objects.create_user('hoi7', 'hoi7@example.com', 'x')
        self.school = School.objects.create(
            name='Bright Minds', slug='bright-charge', admin=user)
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=a_plan(),
            status=SchoolSubscription.STATUS_TRIALING,
            trial_end=timezone.now() + timedelta(days=14),
            has_used_trial=True,
            stripe_subscription_id=SUB_ID,
            invoice_year_start=timezone.now().date(),
        )

    def test_stripe_moving_the_subscription_to_active_activates_the_school(self):
        """Trial ends, the card is charged, Stripe says active."""
        from billing.webhook_handlers import handle_subscription_updated
        now = int(timezone.now().timestamp())
        handle_subscription_updated({'object': {
            'id': SUB_ID, 'status': 'active',
            'metadata': {'type': 'institute', 'school_id': self.school.id},
            'cancel_at_period_end': False,
            'items': {'data': [{'current_period_start': now,
                                'current_period_end': now + 2592000}]},
            'customer': CUSTOMER_ID,
        }})
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertIsNotNone(self.sub.current_period_end)

    def test_it_still_activates_when_stripe_sends_no_school_metadata(self):
        """The fallback finds it by subscription id."""
        from billing.webhook_handlers import handle_subscription_updated
        now = int(timezone.now().timestamp())
        handle_subscription_updated({'object': {
            'id': SUB_ID, 'status': 'active', 'metadata': {},
            'cancel_at_period_end': False,
            'items': {'data': [{'current_period_start': now,
                                'current_period_end': now + 2592000}]},
            'customer': CUSTOMER_ID,
        }})
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SchoolSubscription.STATUS_ACTIVE)

    def test_an_expired_trial_walls_the_school_off(self):
        """The trial running out without payment must still block access."""
        SchoolSubscription.objects.filter(pk=self.sub.pk).update(
            trial_end=timezone.now() - timedelta(days=1))
        self.sub.refresh_from_db()
        from cwa_classroom.middleware import TrialExpiryMiddleware
        self.assertTrue(TrialExpiryMiddleware._is_school_sub_expired(self.sub))


@override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
class Step8_AFullyFreeCodeNeedsNoCard(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_teacher_center')
        self.plan = a_plan()
        self.code = InstituteDiscountCode.objects.create(
            code='ALLFREE', discount_percent=100, is_active=True)

    @patch('stripe.checkout.Session.create')
    def test_the_account_is_built_immediately_and_stripe_untouched(self, mock_create):
        resp = self.client.post(self.url, form(plan_id=self.plan.id,
                                               discount_code='ALLFREE'))
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('stripe.com', resp.url)
        mock_create.assert_not_called()

        school = School.objects.get(name='Bright Minds Academy')
        self.assertEqual(school.subscription.status,
                         SchoolSubscription.STATUS_ACTIVE)
        self.assertIsNone(school.subscription.trial_end)
        self.assertEqual(PendingInstituteRegistration.objects.count(), 0)

    @patch('stripe.checkout.Session.create')
    def test_the_code_use_is_counted(self, _mock):
        self.client.post(self.url, form(plan_id=self.plan.id,
                                        discount_code='ALLFREE'))
        self.code.refresh_from_db()
        self.assertEqual(self.code.uses, 1)
