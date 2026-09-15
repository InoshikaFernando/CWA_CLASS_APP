"""Getting a discount code onto a school, and onto the invoice.

Three holes, all of them silent, all of them about money:

1. A code could be created and never attached. The only code that ever reached
   a SchoolSubscription was one typed at registration, so granting an existing
   school a deal meant editing the row in Django admin — no audit trail, no
   redemption counted, and the super-admin page that offers every other
   override offered nothing for this.

2. ``InstituteCheckoutView`` never passed the coupon. A school whose
   subscription recorded "50% off" was sent to Stripe at list price and
   charged it; the discount existed only in our database. For a 100% code,
   which deliberately has no Stripe coupon at all, the school was billed in
   full for a plan it had been granted free.

3. The billing portal's ``return_url`` came from ``HTTP_REFERER``, so whoever
   linked to the portal chose where the school's billing admin landed after
   it — an off-site redirect handed out by a request header.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from billing.models import InstituteDiscountCode, InstitutePlan, SchoolSubscription
from classroom.models import School


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(**kwargs):
    defaults = dict(
        name='Platinum', slug='platinum', price=Decimal('189.00'),
        stripe_price_id='price_platinum', class_limit=10, student_limit=100,
        invoice_limit_yearly=200, extra_invoice_rate=Decimal('0.30'),
        trial_days=14,
    )
    defaults.update(kwargs)
    return InstitutePlan.objects.create(**defaults)


def _code(code='CWAFREE100', percent=100, **kwargs):
    return InstituteDiscountCode.objects.create(
        code=code, discount_percent=percent, **kwargs,
    )


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


# ===========================================================================
# 1. The super-admin grant
# ===========================================================================

class ApplyDiscountAdminTests(TestCase):

    def setUp(self):
        self.superuser = CustomUser.objects.create_superuser(
            username='super', password='testpass123', email='super@test.com',
        )
        self.client.login(username='super', password='testpass123')
        self.school = School.objects.create(
            name='Code Wizards Aotearoa', slug='cwa', admin=self.superuser,
        )
        self.plan = _plan()
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan, status='active',
        )
        self.url = reverse('billing_admin_subscription_override',
                           args=[self.sub.pk])

    def _apply(self, code, **extra):
        return self.client.post(self.url, {
            'action': 'apply_discount',
            'discount_code_id': code.pk if code else '',
            **extra,
        })

    def test_a_full_discount_is_attached_and_the_redemption_counted(self):
        code = _code()
        resp = self._apply(code)

        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        code.refresh_from_db()
        self.assertEqual(self.sub.discount_code, code)
        self.assertEqual(code.uses, 1)
        self.assertTrue(AuditLog.objects.filter(
            action='subscription_discount_applied').exists())

    def test_reapplying_the_same_code_counts_one_redemption(self):
        """Otherwise a max_uses=1 code looks exhausted by a second click."""
        code = _code()
        self._apply(code)
        self._apply(code)

        code.refresh_from_db()
        self.assertEqual(code.uses, 1)

    def test_clearing_removes_the_code_but_not_the_redemption(self):
        code = _code()
        self._apply(code)

        resp = self._apply(None)

        self.sub.refresh_from_db()
        code.refresh_from_db()
        self.assertIsNone(self.sub.discount_code)
        # A redemption that happened is not undone by withdrawing the benefit.
        self.assertEqual(code.uses, 1)
        self.assertTrue(AuditLog.objects.filter(
            action='subscription_discount_cleared').exists())
        self.assertIn('Discount code removed.', _messages(resp))

    def test_an_unknown_code_changes_nothing(self):
        resp = self.client.post(self.url, {
            'action': 'apply_discount', 'discount_code_id': '999999',
        })

        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.discount_code)
        self.assertIn('Discount code not found.', _messages(resp))

    def test_a_non_numeric_code_id_is_an_error_not_a_crash(self):
        resp = self.client.post(self.url, {
            'action': 'apply_discount', 'discount_code_id': 'not-an-id',
        })

        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.discount_code)
        self.assertIn('Discount code not found.', _messages(resp))

    def test_a_partial_code_with_no_stripe_coupon_is_refused(self):
        """Recording a discount Stripe cannot honour promises what we then
        fail to deliver — the school is charged list price regardless."""
        code = _code('HALFOFF', 50)

        with patch('billing.stripe_service.ensure_stripe_coupon',
                   return_value=(False, 'Stripe is not configured')) as ensure:
            resp = self._apply(code)

        ensure.assert_called_once()
        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.discount_code)
        self.assertTrue(any('no Stripe coupon' in m for m in _messages(resp)))

    def test_a_partial_code_reaches_a_live_stripe_subscription(self):
        code = _code('HALFOFF', 50, stripe_coupon_id='co_half')
        self.sub.stripe_subscription_id = 'sub_live'
        self.sub.save(update_fields=['stripe_subscription_id'])

        with patch('billing.stripe_service.ensure_stripe_coupon',
                   return_value=(True, None)), \
             patch('billing.stripe_service.add_subscription_discount',
                   return_value=(True, None)) as add:
            self._apply(code)

        add.assert_called_once_with('sub_live', 'co_half', None)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.discount_code, code)

    def test_a_coupon_stripe_refuses_is_reported_not_swallowed(self):
        code = _code('HALFOFF', 50, stripe_coupon_id='co_half')
        self.sub.stripe_subscription_id = 'sub_live'
        self.sub.save(update_fields=['stripe_subscription_id'])

        with patch('billing.stripe_service.ensure_stripe_coupon',
                   return_value=(True, None)), \
             patch('billing.stripe_service.add_subscription_discount',
                   return_value=(False, 'EARLYBIRD discounts everything')):
            resp = self._apply(code)

        self.assertTrue(any('still bills the full amount' in m
                            for m in _messages(resp)))

    def test_a_full_discount_says_a_live_subscription_keeps_charging(self):
        """The code stops us starting a charge; it does not stop one running."""
        code = _code()
        self.sub.stripe_subscription_id = 'sub_live'
        self.sub.save(update_fields=['stripe_subscription_id'])

        resp = self._apply(code)

        self.assertTrue(any('will keep charging' in m for m in _messages(resp)))

    def test_the_attached_code_is_offered_even_when_inactive(self):
        """Listing only active codes would render the select with nothing
        chosen, so saving the form would silently strip the deal."""
        code = _code('OLDDEAL', 100, is_active=False)
        self.sub.discount_code = code
        self.sub.save(update_fields=['discount_code'])

        resp = self.client.get(
            reverse('billing_admin_subscription_detail', args=[self.sub.pk]))

        # The option itself, selected — the Details card names the code either
        # way, so asserting on the code alone would pass without the fix.
        self.assertContains(resp, f'<option value="{code.pk}" selected>',
                            html=False)
        self.assertIn(code, resp.context['discount_codes'])

    def test_a_normal_user_cannot_grant_a_discount(self):
        CustomUser.objects.create_user(
            username='normal', password='testpass123', email='n@test.com')
        self.client.login(username='normal', password='testpass123')
        code = _code()

        self._apply(code)

        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.discount_code)


# ===========================================================================
# 2. Checkout honouring the code it already holds
# ===========================================================================

class InstituteCheckoutDiscountTests(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='hoi', password='testpass123', email='hoi@test.com',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=self.user, role=role)
        self.client.login(username='hoi', password='testpass123')
        self.school = School.objects.create(
            name='Code Wizards Aotearoa', slug='cwa', admin=self.user,
        )
        self.plan = _plan()
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=self.plan, status='trialing',
        )
        self.url = reverse('institute_checkout')

    def _attach(self, code):
        self.sub.discount_code = code
        self.sub.save(update_fields=['discount_code'])

    def test_a_full_discount_activates_the_plan_without_visiting_stripe(self):
        self._attach(_code())

        with patch('billing.stripe_service.create_institute_checkout_session'
                   ) as session:
            resp = self.client.post(self.url, {'plan': 'platinum'})

        session.assert_not_called()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SchoolSubscription.STATUS_ACTIVE)
        self.assertIsNone(self.sub.trial_end)
        self.assertEqual(self.sub.plan, self.plan)
        self.assertRedirects(resp, reverse('institute_subscription_dashboard'),
                             fetch_redirect_response=False)

    def test_a_full_discount_works_even_with_no_stripe_price_on_the_plan(self):
        """Nothing is charged, so a missing price id must not block the grant."""
        self.plan.stripe_price_id = ''
        self.plan.save(update_fields=['stripe_price_id'])
        self._attach(_code())

        self.client.post(self.url, {'plan': 'platinum'})

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SchoolSubscription.STATUS_ACTIVE)

    def test_the_coupon_is_passed_to_the_checkout_session(self):
        self._attach(_code('EARLYBIRD', 50, stripe_coupon_id='co_early'))

        with patch('billing.stripe_service.ensure_stripe_coupon',
                   return_value=(True, None)), \
             patch('billing.stripe_service.create_institute_checkout_session',
                   return_value=MagicMock(url='https://stripe.test/co', id='cs_1')
                   ) as session:
            self.client.post(self.url, {'plan': 'platinum'})

        self.assertEqual(session.call_args.kwargs['stripe_coupon_id'], 'co_early')

    def test_checkout_is_refused_when_the_coupon_could_not_be_created(self):
        """Better no charge than the full charge against a discounted row."""
        self._attach(_code('EARLYBIRD', 50))

        with patch('billing.stripe_service.ensure_stripe_coupon',
                   return_value=(False, 'Stripe is not configured')), \
             patch('billing.stripe_service.create_institute_checkout_session'
                   ) as session:
            resp = self.client.post(self.url, {'plan': 'platinum'})

        session.assert_not_called()
        self.assertTrue(any('could not be applied' in m for m in _messages(resp)))
        self.assertRedirects(resp, reverse('institute_plan_select'),
                             fetch_redirect_response=False)

    def test_a_school_with_no_code_still_checks_out(self):
        with patch('billing.stripe_service.create_institute_checkout_session',
                   return_value=MagicMock(url='https://stripe.test/co', id='cs_1')
                   ) as session:
            self.client.post(self.url, {'plan': 'platinum'})

        self.assertIsNone(session.call_args.kwargs['stripe_coupon_id'])


# ===========================================================================
# 3. Where Stripe sends them back to
# ===========================================================================

class BillingPortalReturnUrlTests(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='hoi', password='testpass123', email='hoi@test.com',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=self.user, role=role)
        self.client.login(username='hoi', password='testpass123')
        self.school = School.objects.create(
            name='Code Wizards Aotearoa', slug='cwa', admin=self.user,
        )
        self.sub = SchoolSubscription.objects.create(
            school=self.school, plan=_plan(), status='active',
            stripe_customer_id='cus_1',
        )

    def test_a_referer_cannot_choose_where_stripe_returns_them(self):
        with patch('billing.stripe_service.create_billing_portal_session',
                   return_value=MagicMock(url='https://stripe.test/portal')
                   ) as portal:
            self.client.get(reverse('stripe_billing_portal'),
                            HTTP_REFERER='https://evil.example/phish')

        return_url = portal.call_args[0][1]
        self.assertNotIn('evil.example', return_url)
        self.assertTrue(
            return_url.endswith(reverse('institute_subscription_dashboard')),
            f'unexpected return_url: {return_url}',
        )
