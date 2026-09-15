"""The coupon form can build a limited free promotion, not just a permanent one.

A "two weeks free, without the AI questions" offer is three fields that have to
agree: 100% off, Student Basic, and an access duration. The form could set the
first two and not the third — ``grant_days`` was parsed for a Student (Promo)
code only, and shown for one only — so the combination every timed promotion
needs could not be built here at all.

What made it worth fixing rather than documenting: the failure is silent and
points the wrong way. You tick Student Basic meaning "a fortnight", leave the
field you never saw blank, and the code you hand out grants the free edition
**forever**. Nothing errors, the code works, students redeem it, and the only
way to find out is to notice months later that nobody was ever asked to pay.

A permanent free tier is still allowed — CWA's own free students are on exactly
that — so the guard is a warning, not a refusal.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from billing.models import DiscountCode, Package, PromoCode

User = get_user_model()


class CouponFormBuildsATimedPromotion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='coupon_root', email='coupon_root@test.local',
            password='TestPass123!')
        cls.package = Package.objects.create(
            name='Wizard', price=19.90, stripe_price_id='price_coupon_test')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)
        self.url = reverse('billing_admin_coupon_create')

    def _post(self, **overrides):
        data = {
            'code': 'MHM2WEEKS',
            'description': 'MHM free fortnight',
            'target_type': 'student_discount',
            'discount_percent': '100',
            'duration': 'forever',
            'max_uses': '200',
            'grant_days': '14',
            'grants_student_basic': '1',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    # -- the combination that could not be built ----------------------------

    def test_it_creates_a_100_percent_14_day_student_basic_code(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)

        code = DiscountCode.objects.get(code='MHM2WEEKS')
        self.assertEqual(code.discount_percent, 100)
        self.assertEqual(code.grant_days, 14, 'the window was dropped again')
        self.assertTrue(code.grants_student_basic)
        self.assertEqual(code.max_uses, 200)

    def test_the_window_survives_without_the_tier(self):
        """A plain timed free code — no Student Basic, still 14 days."""
        self._post(code='PLAIN14', grants_student_basic='')

        code = DiscountCode.objects.get(code='PLAIN14')
        self.assertEqual(code.grant_days, 14)
        self.assertFalse(code.grants_student_basic)

    def test_a_promo_code_still_gets_its_window(self):
        """The type that always worked must keep working."""
        self._post(code='PROMO30', target_type='student_promo',
                   grants_student_basic='', grant_days='30', class_limit='0')

        self.assertEqual(PromoCode.objects.get(code='PROMO30').grant_days, 30)

    # -- validation ---------------------------------------------------------

    def test_zero_days_is_refused(self):
        response = self._post(grant_days='0')

        self.assertEqual(response.status_code, 200)
        self.assertIn('grant_days', response.context['errors'])
        self.assertFalse(DiscountCode.objects.filter(code='MHM2WEEKS').exists())

    def test_a_non_number_is_refused(self):
        response = self._post(grant_days='two weeks')

        self.assertEqual(response.status_code, 200)
        self.assertIn('grant_days', response.context['errors'])
        self.assertFalse(DiscountCode.objects.filter(code='MHM2WEEKS').exists())

    def test_a_charging_code_still_cannot_carry_the_tier(self):
        """Unchanged, and the reason Student Basic is 100%-only."""
        response = self._post(discount_percent='50')

        self.assertEqual(response.status_code, 200)
        self.assertIn('grants_student_basic', response.context['errors'])

    # -- the permanent case is allowed, but said out loud -------------------

    def test_the_tier_with_no_window_is_created_and_warned_about(self):
        response = self._post(grant_days='')

        code = DiscountCode.objects.get(code='MHM2WEEKS')
        self.assertIsNone(code.grant_days)
        self.assertTrue(code.grants_student_basic,
                        'a permanent free tier is legitimate and must still be '
                        'creatable')

        warnings = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(
            any('never expires' in w for w in warnings),
            f'expected a warning that the code never expires, got {warnings}')

    def test_no_warning_when_a_window_was_set(self):
        response = self._post()

        warnings = [str(m) for m in response.wsgi_request._messages]
        self.assertFalse(any('never expires' in w for w in warnings))

    def test_no_warning_for_an_ordinary_permanent_free_code(self):
        """Only the Student Basic combination is worth warning about."""
        response = self._post(code='FREEFOREVER', grant_days='',
                              grants_student_basic='')

        warnings = [str(m) for m in response.wsgi_request._messages]
        self.assertFalse(any('never expires' in w for w in warnings))

    # -- the created code behaves, end to end -------------------------------

    def test_the_code_the_form_builds_is_the_one_the_command_builds(self):
        """Same three fields, whichever route the owner took."""
        from io import StringIO

        from django.core.management import call_command

        self._post(code='VIA_FORM')
        call_command('free_trial_code', '--code', 'VIA_COMMAND',
                     '--days', '14', '--max-uses', '200',
                     stdout=StringIO(), stderr=StringIO())

        form_code = DiscountCode.objects.get(code='VIA_FORM')
        command_code = DiscountCode.objects.get(code='VIA_COMMAND')

        for field in ('discount_percent', 'grant_days',
                      'grants_student_basic', 'max_uses', 'is_active'):
            self.assertEqual(
                getattr(form_code, field), getattr(command_code, field),
                f'{field} differs between the form and the command')

    def test_redeeming_the_form_built_code_ends_after_its_window(self):
        """The window is only real if it reaches the subscription."""
        from datetime import timedelta

        from django.utils import timezone

        from accounts.models import Role, UserRole
        from billing.entitlements import sync_student_modules
        from billing.models import StudentModule, Subscription
        from worksheets.grading_service import student_can_be_ai_graded

        self._post()
        code = DiscountCode.objects.get(code='MHM2WEEKS')

        role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'})
        student = User.objects.create_user(
            username='form_redeemer', email='form_redeemer@test.local',
            password='TestPass123!')
        UserRole.objects.create(user=student, role=role)

        sub = Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_ACTIVE, discount_code=code,
            discount_percent_snapshot=100,
            trial_end=timezone.now() + timedelta(days=code.grant_days),
        )
        sync_student_modules(sub)

        self.assertIn(StudentModule.MODULE_BASIC,
                      {m.module for m in sub.student_modules.all()})
        self.assertFalse(student_can_be_ai_graded(student))
        self.assertFalse(sub.free_grant_has_lapsed)

        Subscription.objects.filter(pk=sub.pk).update(
            trial_end=timezone.now() - timedelta(days=1))
        sub.refresh_from_db()
        self.assertTrue(sub.free_grant_has_lapsed)


class OnlyASuperuserCanMintCodes(TestCase):

    def test_an_ordinary_user_is_turned_away(self):
        user = User.objects.create_user(
            username='not_root', email='not_root@test.local',
            password='TestPass123!')
        client = Client()
        client.force_login(user)

        response = client.post(reverse('billing_admin_coupon_create'), {
            'code': 'SNEAKY', 'target_type': 'student_discount',
            'discount_percent': '100', 'grant_days': '14',
            'grants_student_basic': '1', 'duration': 'forever',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('subjects_hub'), response.url)
        self.assertFalse(DiscountCode.objects.filter(code='SNEAKY').exists())
