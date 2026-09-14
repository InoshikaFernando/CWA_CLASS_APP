"""The MHM promotion: two weeks free, no card, no AI — then it stops and asks.

The promise made to a cohort of students is four separate things, and each one
of them used to fail in a way that made no noise at all:

1. **No card details.** A 100%-off code skips Stripe entirely, so nothing ever
   asks for one. This held already; it is pinned here because it is the part a
   future change to the checkout flow would break silently, and a promotion that
   suddenly asks a fourteen-year-old for a card is not a bug you find in a log.
2. **No AI-graded questions.** The free edition is the questions the app marks
   for itself. Also held already, via ``grants_student_basic``.
3. **It stops after fourteen days.** This did not hold, three different ways —
   see :class:`TheFreeWindowActuallyEnds`.
4. **Paying upgrades them.** This did not hold at all, and the failure was worse
   than nothing happening — see :class:`PayingUpgradesOffStudentBasic`.

The tests are grouped by promise rather than by module, because the promise is
the thing that has to survive: any one of these going red means a student was
told something untrue.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from io import StringIO

from accounts.models import Role, UserRole
from billing.entitlements import (
    active_student_modules, grant_student_module, sync_student_modules,
    upgrade_student_from_basic,
)
from billing.models import (
    DiscountCode, Package, Payment, PromoCode, StudentModule, Subscription,
)
from classroom.models import School, SchoolStudent
from cwa_classroom.middleware import TrialExpiryMiddleware
from worksheets.grading_service import student_can_be_ai_graded

User = get_user_model()

#: What the middleware's ``get_response`` returns when a request is NOT blocked.
SENTINEL = object()

MHM_CODE = 'MHM2WEEKS'


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.title()})
    return role


def _user(username, role_name=Role.STUDENT, **kwargs):
    user = User.objects.create_user(
        username=username, email=f'{username}@test.local',
        password='TestPass123!', **kwargs)
    UserRole.objects.create(user=user, role=_role(role_name))
    return user


def _paid_package():
    package, _ = Package.objects.get_or_create(
        name='Student Monthly',
        defaults={'price': 19.90, 'class_limit': 0,
                  'stripe_price_id': 'price_mhm_test', 'is_default': True},
    )
    return package


def _mint(code=MHM_CODE, days=14, **kwargs):
    """The code the command produces, built directly so a test of one promise
    does not fail because a different promise's command broke."""
    defaults = dict(discount_percent=100, grant_days=days,
                    grants_student_basic=True, is_active=True)
    defaults.update(kwargs)
    return DiscountCode.objects.create(code=code, **defaults)


# ---------------------------------------------------------------------------
# 1. Minting the code
# ---------------------------------------------------------------------------

class MintingTheCode(TestCase):
    """``free_trial_code`` sets the three fields that have to agree.

    Each of them fails quietly on its own: a code that charges cannot carry the
    free tier, a code with no ``grant_days`` never ends, and a code without
    ``grants_student_basic`` hands out the AI-graded questions at the vendor's
    per-answer cost. Nothing warns you about any of the three.
    """

    def _run(self, *args, **kwargs):
        out = StringIO()
        call_command('free_trial_code', *args, stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def test_it_mints_a_fourteen_day_free_no_ai_code(self):
        self._run('--code', MHM_CODE, '--max-uses', '200')

        code = DiscountCode.objects.get(code=MHM_CODE)
        self.assertEqual(code.discount_percent, 100)
        self.assertEqual(code.grant_days, 14)
        self.assertTrue(code.grants_student_basic)
        self.assertEqual(code.max_uses, 200)
        self.assertTrue(code.is_active)
        # A 100% code never reaches Stripe, so a coupon id on it would describe
        # a discount being applied somewhere that it is not.
        self.assertEqual(code.stripe_coupon_id, '')

    def test_fourteen_days_is_the_default_and_days_overrides_it(self):
        self._run('--code', 'DEFAULTDAYS')
        self.assertEqual(
            DiscountCode.objects.get(code='DEFAULTDAYS').grant_days, 14)

        self._run('--code', 'TERM4', '--days', '21')
        self.assertEqual(DiscountCode.objects.get(code='TERM4').grant_days, 21)

    def test_the_code_is_upper_cased_so_students_can_type_it_any_way(self):
        self._run('--code', 'mhm-lower')
        self.assertTrue(DiscountCode.objects.filter(code='MHM-LOWER').exists())

    def test_dry_run_writes_nothing(self):
        output = self._run('--code', MHM_CODE, '--dry-run')
        self.assertFalse(DiscountCode.objects.filter(code=MHM_CODE).exists())
        self.assertIn('DRY RUN', output)

    def test_rerunning_updates_in_place_rather_than_failing(self):
        """A cohort is often set up twice — once wrong, once right."""
        self._run('--code', MHM_CODE, '--max-uses', '50')
        self._run('--code', MHM_CODE, '--max-uses', '300')

        self.assertEqual(DiscountCode.objects.filter(code=MHM_CODE).count(), 1)
        self.assertEqual(
            DiscountCode.objects.get(code=MHM_CODE).max_uses, 300)

    def test_expires_is_the_last_day_to_START_not_when_access_ends(self):
        """A student who starts on the final day still gets the full window."""
        self._run('--code', MHM_CODE, '--expires', '2026-12-19')

        code = DiscountCode.objects.get(code=MHM_CODE)
        self.assertEqual(timezone.localtime(code.expires_at).date().isoformat(),
                         '2026-12-19')
        # Still redeemable during that day, not expired from midnight.
        self.assertTrue(code.expires_at > timezone.make_aware(
            timezone.datetime(2026, 12, 19, 12, 0)))

    def test_a_bad_expiry_is_refused_rather_than_silently_ignored(self):
        with self.assertRaises(CommandError):
            self._run('--code', MHM_CODE, '--expires', '19-12-2026')
        self.assertFalse(DiscountCode.objects.filter(code=MHM_CODE).exists())

    def test_zero_days_is_refused(self):
        """``--days 0`` would read as "free forever" once written."""
        with self.assertRaises(CommandError):
            self._run('--code', MHM_CODE, '--days', '0')

    def test_with_ai_mints_the_full_app_instead(self):
        self._run('--code', 'FULLFREE', '--with-ai')
        self.assertFalse(
            DiscountCode.objects.get(code='FULLFREE').grants_student_basic)

    def test_deactivating_stops_new_redemptions_and_keeps_the_old_ones(self):
        self._run('--code', MHM_CODE)
        DiscountCode.objects.filter(code=MHM_CODE).update(uses=17)

        self._run('--code', MHM_CODE, '--deactivate')

        code = DiscountCode.objects.get(code=MHM_CODE)
        self.assertFalse(code.is_active)
        self.assertFalse(code.is_valid())
        self.assertEqual(code.uses, 17, 'redemption history must survive')

    def test_it_refuses_to_add_the_tier_to_a_code_students_already_hold(self):
        """The one thing that reaches backwards, so the model forbids it.

        The tier is resolved from the code every time one of those students is
        re-activated, so flipping the flag changes what people who were promised
        the full app get — next time they re-checkout, or next time the success
        page runs. A new promotion needs a new code.
        """
        DiscountCode.objects.create(
            code='ALREADYOUT', discount_percent=100, grants_student_basic=False,
            uses=9)

        with self.assertRaises(CommandError) as ctx:
            self._run('--code', 'ALREADYOUT')

        self.assertIn('already been redeemed', str(ctx.exception))
        self.assertFalse(
            DiscountCode.objects.get(code='ALREADYOUT').grants_student_basic,
            'the refusal must leave the code exactly as it was')


# ---------------------------------------------------------------------------
# 2. No card details
# ---------------------------------------------------------------------------

class NoCardIsEverAskedFor(TestCase):
    """Nothing in the free flow reaches Stripe, in either redemption route.

    Two entirely separate views take a code — ``ApplyPromoCodeView`` for a
    student at checkout, ``CompleteProfileView`` for a school student finishing
    their profile — so both are pinned. A regression in either one puts a card
    form in front of a child whose parent was told there would not be one.
    """

    def setUp(self):
        self.package = _paid_package()
        self.code = _mint()

    # -- the school-student route (the one MHM students take) ---------------

    def _school_student(self):
        admin = User.objects.create_user(
            username='mhm_admin', email='mhm_admin@test.local',
            password='TestPass123!')
        school = School.objects.create(
            name='MHM', slug='mhm', admin=admin)
        student = _user('mhm_kid', Role.STUDENT, profile_completed=False)
        SchoolStudent.objects.create(school=school, student=student,
                                     is_active=True)
        return student

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer',
           return_value='cus_should_never_happen')
    def test_redeeming_never_creates_a_stripe_checkout_session(
            self, mock_customer, mock_session):
        student = self._school_student()
        client = Client()
        client.force_login(student)

        client.post(reverse('complete_profile'), {
            'first_name': 'Free', 'last_name': 'Student',
            'discount_code': MHM_CODE,
        })

        mock_session.assert_not_called()
        mock_customer.assert_not_called()

    def test_the_subscription_holds_no_stripe_ids_and_no_payment_row(self):
        student = self._school_student()
        client = Client()
        client.force_login(student)

        client.post(reverse('complete_profile'), {
            'first_name': 'Free', 'last_name': 'Student',
            'discount_code': MHM_CODE,
        })

        sub = Subscription.objects.get(user=student)
        self.assertEqual(sub.stripe_subscription_id, '')
        self.assertEqual(sub.stripe_customer_id, '')
        self.assertFalse(Payment.objects.filter(user=student).exists())
        self.assertTrue(sub.is_free_grant)

    def test_the_student_is_let_straight_in(self):
        """No card means no payment step: they work the same day."""
        student = self._school_student()
        client = Client()
        client.force_login(student)

        response = client.post(reverse('complete_profile'), {
            'first_name': 'Free', 'last_name': 'Student',
            'discount_code': MHM_CODE,
        })

        student.refresh_from_db()
        self.assertTrue(student.profile_completed)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('subjects_hub'), response.url)

    # -- the checkout route --------------------------------------------------

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    def test_applying_the_code_at_checkout_skips_stripe_too(self, mock_session):
        student = _user('mhm_individual', Role.INDIVIDUAL_STUDENT)
        client = Client()
        client.force_login(student)

        response = client.post(
            reverse('apply_promo_code', args=[self.package.id]),
            data='{"code": "%s"}' % MHM_CODE,
            content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['fully_free'])
        self.assertEqual(response.json()['grant_days'], 14)
        mock_session.assert_not_called()
        self.assertEqual(
            Subscription.objects.get(user=student).stripe_subscription_id, '')


# ---------------------------------------------------------------------------
# 3. No AI-graded questions while the promotion runs
# ---------------------------------------------------------------------------

class TheFreeEditionSkipsAIGrading(TestCase):

    def setUp(self):
        self.package = _paid_package()
        self.code = _mint()
        self.student = _user('no_ai_kid', Role.INDIVIDUAL_STUDENT)

    def _redeem(self):
        sub = Subscription.objects.create(
            user=self.student, package=self.package,
            status=Subscription.STATUS_TRIALING,
            trial_end=timezone.now() + timedelta(days=14),
            discount_code=self.code, discount_percent_snapshot=100)
        sync_student_modules(sub)
        return sub

    def test_a_student_on_the_promotion_is_never_sent_to_the_grader(self):
        self._redeem()
        self.assertFalse(student_can_be_ai_graded(self.student))
        self.assertIn(StudentModule.MODULE_BASIC,
                      active_student_modules(self.student))

    def test_a_student_on_no_promotion_is_unaffected(self):
        """The control: every student on the site today holds no module."""
        Subscription.objects.create(
            user=self.student, package=self.package,
            status=Subscription.STATUS_ACTIVE)
        self.assertTrue(student_can_be_ai_graded(self.student))

    def test_a_code_without_the_flag_grants_the_app_in_full(self):
        plain = _mint(code='PLAIN14', grants_student_basic=False)
        sub = Subscription.objects.create(
            user=self.student, package=self.package,
            status=Subscription.STATUS_TRIALING, discount_code=plain,
            trial_end=timezone.now() + timedelta(days=14))
        sync_student_modules(sub)
        self.assertTrue(student_can_be_ai_graded(self.student))

    def test_a_charging_code_can_never_carry_the_free_tier(self):
        """The model refuses it, so a paying student cannot be quietly reduced."""
        from django.core.exceptions import ValidationError

        code = DiscountCode(code='HALFPRICE', discount_percent=50,
                            grants_student_basic=True)
        with self.assertRaises(ValidationError):
            code.full_clean(exclude=['applicable_packages'])


# ---------------------------------------------------------------------------
# 4. The window actually ends
# ---------------------------------------------------------------------------

class TheFreeWindowActuallyEnds(TestCase):
    """Fourteen days meant fourteen days in only one of four situations.

    * A school student's redemption never wrote ``trial_end`` at all —
      ``grant_days`` was read on every other route and dropped on that one.
    * ``_check_personal_subscription`` asked ``is_active_or_trialing``, which
      reads the status word and never the date, so a school student was not
      stopped even when the date existed.
    * ``_is_trial_expired`` returned False for ``active`` before looking at the
      date, and the 100%-off ``PromoCode`` branch writes ``active``.
    * Only individual students were checked against a date at all.

    Each of those is free-forever, and none of them logs anything.
    """

    @classmethod
    def setUpTestData(cls):
        cls.package = _paid_package()
        admin = User.objects.create_user(
            username='wall_admin', email='wall_admin@test.local',
            password='TestPass123!')
        cls.school = School.objects.create(
            name='Wall School', slug='wall-school', admin=admin)

    def setUp(self):
        self.code = _mint()
        self.rf = RequestFactory()
        self.mw = TrialExpiryMiddleware(lambda request: SENTINEL)

    def _run(self, user, path='/hub/'):
        request = self.rf.get(path)
        request.user = user
        return self.mw(request)

    def _assert_walled(self, response):
        self.assertIsNot(response, SENTINEL,
                         'expected the payment wall, got straight through')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/trial-expired/', response.url)

    def _assert_allowed(self, response):
        self.assertIs(response, SENTINEL,
                      'expected to be let through, got the payment wall')

    # -- the window is written down in the first place ----------------------

    def test_redeeming_as_a_school_student_records_the_fourteen_days(self):
        student = _user('dated_kid', Role.STUDENT, profile_completed=False)
        SchoolStudent.objects.create(school=self.school, student=student,
                                     is_active=True)
        client = Client()
        client.force_login(student)

        client.post(reverse('complete_profile'), {
            'first_name': 'Dated', 'last_name': 'Student',
            'discount_code': MHM_CODE,
        })

        sub = Subscription.objects.get(user=student)
        self.assertIsNotNone(
            sub.trial_end,
            'grant_days was dropped here, so the promotion never ended')
        expected = timezone.now() + timedelta(days=14)
        self.assertAlmostEqual(sub.trial_end, expected,
                               delta=timedelta(minutes=5))

    def test_a_free_plan_with_no_window_still_runs_indefinitely(self):
        """A code that names no window must not be given one."""
        forever = DiscountCode.objects.create(
            code='FOREVER', discount_percent=100, grant_days=None)
        student = _user('forever_kid', Role.STUDENT, profile_completed=False)
        SchoolStudent.objects.create(school=self.school, student=student,
                                     is_active=True)
        client = Client()
        client.force_login(student)

        client.post(reverse('complete_profile'), {
            'first_name': 'For', 'last_name': 'Ever',
            'discount_code': forever.code,
        })

        sub = Subscription.objects.get(user=student)
        self.assertIsNone(sub.trial_end)
        self.assertFalse(sub.is_free_grant)
        self._assert_allowed(self._run(student))

    # -- and it is enforced --------------------------------------------------

    def _granted_school_student(self, username, days_ago, status):
        student = _user(username, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student,
                                     is_active=True)
        Subscription.objects.create(
            user=student, package=self.package, status=status,
            discount_code=self.code, discount_percent_snapshot=100,
            trial_end=timezone.now() + timedelta(days=days_ago))
        return student

    def test_day_thirteen_a_school_student_still_works(self):
        student = self._granted_school_student(
            'day13', days_ago=1, status=Subscription.STATUS_ACTIVE)
        self._assert_allowed(self._run(student))

    def test_day_fifteen_a_school_student_is_walled(self):
        """The headline: a school student on a promotion never stopped."""
        student = self._granted_school_student(
            'day15', days_ago=-1, status=Subscription.STATUS_ACTIVE)
        self._assert_walled(self._run(student))

    def test_day_fifteen_a_school_student_on_a_trialing_grant_is_walled(self):
        """The other word the redemption paths write for the same thing."""
        student = self._granted_school_student(
            'day15_trialing', days_ago=-1,
            status=Subscription.STATUS_TRIALING)
        self._assert_walled(self._run(student))

    def test_a_lapsed_promo_code_grant_is_walled_too(self):
        """``ApplyPromoCodeView`` writes ``active`` with an end date."""
        PromoCode.objects.create(code='PROMO14', discount_percent=100,
                                 grants_student_basic=True, grant_days=14)
        student = _user('promo_lapsed', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student,
                                     is_active=True)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_ACTIVE, promo_code_used='PROMO14',
            trial_end=timezone.now() - timedelta(days=1))

        self._assert_walled(self._run(student))

    def test_an_individual_student_is_walled_at_the_end_too(self):
        student = _user('individual_lapsed', Role.INDIVIDUAL_STUDENT)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_ACTIVE, discount_code=self.code,
            trial_end=timezone.now() - timedelta(days=1))

        self._assert_walled(self._run(student))

    def test_the_lapse_is_recorded_on_the_subscription(self):
        """So the status column stops disagreeing with the access they have."""
        student = self._granted_school_student(
            'stamped', days_ago=-1, status=Subscription.STATUS_ACTIVE)

        self._run(student)

        self.assertEqual(Subscription.objects.get(user=student).status,
                         Subscription.STATUS_EXPIRED)

    def test_a_real_stripe_status_is_never_overwritten(self):
        """``past_due`` is Stripe's to own — the wall says "update your card"."""
        student = _user('pastdue_kid', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student,
                                     is_active=True)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_PAST_DUE,
            stripe_subscription_id='sub_real')

        self._assert_walled(self._run(student))
        self.assertEqual(Subscription.objects.get(user=student).status,
                         Subscription.STATUS_PAST_DUE)

    def test_a_paying_subscriber_is_never_touched_by_any_of_this(self):
        """A Stripe trial has a trial_end too, and must not read as a grant."""
        student = _user('paying_kid', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student,
                                     is_active=True)
        sub = Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id='sub_paid',
            trial_end=timezone.now() - timedelta(days=90))

        self.assertFalse(sub.is_free_grant)
        self._assert_allowed(self._run(student))

    # -- and the wall asks them to pay, in the right words -------------------

    def test_the_wall_lets_them_through_to_billing_to_subscribe(self):
        student = self._granted_school_student(
            'can_pay', days_ago=-1, status=Subscription.STATUS_ACTIVE)
        self._assert_allowed(self._run(student, path='/billing/'))
        self._assert_allowed(
            self._run(student, path='/accounts/trial-expired/'))

    def test_the_wall_says_the_promotion_ended_not_the_trial_expired(self):
        """They never had a trial. ``is_promo_activated`` could not tell:
        it reads ``promo_code_used``, which a DiscountCode never writes."""
        student = self._granted_school_student(
            'worded', days_ago=-1, status=Subscription.STATUS_ACTIVE)
        client = Client()
        client.force_login(student)

        response = client.get(reverse('trial_expired'))

        self.assertEqual(response.context['reason'], 'promo_ended')
        self.assertContains(response, 'Your promotion has ended')

    def test_an_ordinary_expired_trial_still_reads_as_a_trial(self):
        student = _user('real_trial', Role.INDIVIDUAL_STUDENT)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_EXPIRED,
            stripe_subscription_id='sub_trial')
        client = Client()
        client.force_login(student)

        self.assertEqual(
            client.get(reverse('trial_expired')).context['reason'], 'expired')

    def test_the_block_is_audit_logged_as_a_promotion_ending(self):
        from audit.models import AuditLog

        student = self._granted_school_student(
            'audited', days_ago=-1, status=Subscription.STATUS_ACTIVE)
        self._run(student, path='/homework/')

        event = AuditLog.objects.filter(
            user=student, action='subscription_blocked').first()
        self.assertIsNotNone(event)
        self.assertEqual(event.detail.get('reason'), 'personal_promotion_ended')


# ---------------------------------------------------------------------------
# 5. Paying upgrades them
# ---------------------------------------------------------------------------

class PayingUpgradesOffStudentBasic(TestCase):
    """The end of the promotion, and the part that failed worst.

    Nothing moved a student off Student Basic when they paid — and the code that
    put them there is deliberately kept on the subscription forever, because it
    is the answer to "why does this student pay nothing". So the activation read
    that same code back and re-granted Student Basic. A student could pay for
    the full plan and be put straight back on the free edition by the very
    webhook that recorded their payment, with nothing failing anywhere.
    """

    def setUp(self):
        self.package = _paid_package()
        self.code = _mint()
        self.student = _user('upgrader', Role.STUDENT)
        self.sub = Subscription.objects.create(
            user=self.student, package=self.package,
            status=Subscription.STATUS_EXPIRED, discount_code=self.code,
            discount_percent_snapshot=100,
            trial_end=timezone.now() - timedelta(days=1))
        grant_student_module(self.student, StudentModule.MODULE_BASIC,
                             source_code=MHM_CODE)

    def _pay(self):
        self.sub.stripe_subscription_id = 'sub_paid_for_real'
        self.sub.status = Subscription.STATUS_ACTIVE
        self.sub.trial_end = None
        self.sub.save()

    # -- the headline --------------------------------------------------------

    def test_paying_hands_them_the_ai_graded_questions(self):
        self.assertFalse(student_can_be_ai_graded(self.student))

        self._pay()
        upgrade_student_from_basic(self.sub)

        self.assertTrue(student_can_be_ai_graded(self.student))

    def test_student_basic_is_switched_off_and_ai_grading_switched_on(self):
        self._pay()
        upgrade_student_from_basic(self.sub)

        modules = active_student_modules(self.student)
        self.assertNotIn(StudentModule.MODULE_BASIC, modules)
        self.assertIn(StudentModule.MODULE_AI_GRADING, modules)

    def test_the_activation_no_longer_re_grants_the_free_tier(self):
        """The regression: ``sync_student_modules`` on a paid subscription.

        The code is still on the row and always will be. Reading it back here is
        what undid the purchase.
        """
        self._pay()
        sync_student_modules(self.sub)

        self.assertNotIn(StudentModule.MODULE_BASIC,
                         active_student_modules(self.student))
        self.assertTrue(student_can_be_ai_graded(self.student))

    def test_the_record_of_who_was_on_the_promotion_survives(self):
        """Revoked, not deleted — who had what, and when, is kept."""
        self._pay()
        sync_student_modules(self.sub)

        row = StudentModule.objects.get(subscription=self.sub,
                                        module=StudentModule.MODULE_BASIC)
        self.assertFalse(row.is_active)
        self.assertIsNotNone(row.deactivated_at)
        self.assertEqual(row.source_code, MHM_CODE)
        self.assertEqual(self.sub.discount_code, self.code)

    def test_it_is_logged_because_nobody_is_watching_when_it_happens(self):
        from audit.models import AuditLog

        self._pay()
        sync_student_modules(self.sub)

        self.assertTrue(AuditLog.objects.filter(
            user=self.student,
            action='student_basic_upgraded_on_payment').exists())

    # -- and it only ever upgrades ------------------------------------------

    def test_an_unpaid_subscription_is_left_alone(self):
        """Still inside the free window: no Stripe subscription, no upgrade."""
        self.assertIsNone(upgrade_student_from_basic(self.sub))
        self.assertFalse(student_can_be_ai_graded(self.student))

    def test_an_ordinary_payer_is_not_handed_a_module_they_did_not_buy(self):
        """Somebody who was never on Student Basic keeps deciding by school."""
        other = _user('ordinary_payer', Role.STUDENT)
        sub = Subscription.objects.create(
            user=other, package=self.package,
            status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id='sub_ordinary')

        self.assertIsNone(upgrade_student_from_basic(sub))
        self.assertEqual(active_student_modules(other), set())

    def test_running_it_twice_leaves_one_row(self):
        """The webhook and the success page both activate the same payment."""
        self._pay()
        sync_student_modules(self.sub)
        sync_student_modules(self.sub)

        self.assertEqual(
            StudentModule.objects.filter(
                subscription=self.sub,
                module=StudentModule.MODULE_AI_GRADING).count(), 1)
        self.assertTrue(student_can_be_ai_graded(self.student))

    def test_the_upgraded_student_is_let_back_in(self):
        """Paying clears the wall as well as the tier."""
        self._pay()
        sync_student_modules(self.sub)

        rf = RequestFactory()
        request = rf.get('/hub/')
        request.user = self.student
        self.assertIs(
            TrialExpiryMiddleware(lambda r: SENTINEL)(request), SENTINEL)


class TheWholePaymentRoundTripUpgrades(TestCase):
    """Through the real activation entry points, not the helper.

    Two of them, because either can be the one that runs: the Stripe webhook
    normally, and the success page when the webhook is late or lost. A student
    who came off the promotion and paid must end up AI-graded whichever fired —
    the success-page net is new, and the school student had none before it.
    """

    def setUp(self):
        self.package = _paid_package()
        self.code = _mint()
        self.student = _user('roundtrip', Role.STUDENT)
        self.sub = Subscription.objects.create(
            user=self.student, package=self.package,
            status=Subscription.STATUS_EXPIRED, discount_code=self.code,
            discount_percent_snapshot=100,
            trial_end=timezone.now() - timedelta(days=1))
        grant_student_module(self.student, StudentModule.MODULE_BASIC,
                             source_code=MHM_CODE)

    @patch('stripe.Subscription.retrieve')
    def test_the_webhook_upgrades_them(self, mock_retrieve):
        from billing.webhook_handlers import _activate_individual_from_checkout

        mock_retrieve.return_value = MagicMock(status='active',
                                               customer='cus_mhm')

        _activate_individual_from_checkout(
            {'user_id': str(self.student.id),
             'package_id': str(self.package.id),
             'type': 'school_student'},
            'sub_webhook_paid', 'cus_mhm')

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(self.sub.stripe_subscription_id, 'sub_webhook_paid')
        self.assertTrue(student_can_be_ai_graded(self.student))

    @patch('billing.views.stripe.checkout.Session.retrieve')
    def test_the_success_page_upgrades_them_when_the_webhook_is_lost(
            self, mock_retrieve):
        mock_retrieve.return_value = MagicMock(
            payment_status='paid', subscription='sub_success_paid',
            customer='cus_mhm',
            metadata={'package_id': str(self.package.id)})

        client = Client()
        client.force_login(self.student)
        client.get(reverse('complete_profile_payment_success'),
                   {'session_id': 'cs_test_123'})

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.stripe_subscription_id, 'sub_success_paid')
        self.assertTrue(student_can_be_ai_graded(self.student))

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer',
           return_value='cus_mhm')
    def test_the_checkout_carries_the_session_id_back(
            self, mock_customer, mock_session):
        """Without it the success page has nothing to look up, which is the
        whole reason a lost webhook used to cost a student their upgrade."""
        from billing.stripe_service import create_student_checkout_session

        mock_session.return_value = MagicMock(url='https://stripe.test/pay')
        request = RequestFactory().get('/billing/checkout/1/')

        create_student_checkout_session(self.student, self.package, request)

        success_url = mock_session.call_args.kwargs['success_url']
        self.assertIn('session_id={CHECKOUT_SESSION_ID}', success_url)
