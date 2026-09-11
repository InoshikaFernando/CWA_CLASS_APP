"""Two ways the app charged a number it wasn't charging, and a module it gave away.

Both were found by reading a real customer's Stripe invoice by hand, months
after the fact — which is the whole problem. Nothing in the app disagreed with
itself, because nothing compared the two halves:

* **AI Grading Professional, $49/mo, never billed.** The module had no
  ``stripe_price_id``, so ModuleToggleView could not create a subscription item
  and fell through to the local-activation branch — correct for a trialing
  school, and a permanent free gift to a paying one. No log line, no audit row,
  no invoice line.
* **$10 shown, $9 charged.** A Stripe Price is immutable. Editing
  ``ModuleProduct.price`` moves the number on every page in the app and never
  the number on the card; ``sync_stripe_prices`` won't repair it because the row
  already has a price id. Nothing checked the amount — the price health check
  validated existence, active status and currency only.

Plus the third face of the same bug: a blocked school's upsell page quoted a
flat "$10/month" for whichever module had stopped them, while the modules it
gates run from $10 to $149.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from billing.stripe_health import get_stripe_price_health
from classroom.models import School


def _hoi_school(username='unbilled_hoi'):
    user = CustomUser.objects.create_user(
        username=username, password='testpass123', email=f'{username}@test.com',
    )
    role, _ = Role.objects.get_or_create(
        name=Role.HEAD_OF_INSTITUTE,
        defaults={'display_name': 'Head Of Institute'},
    )
    UserRole.objects.create(user=user, role=role)
    school = School.objects.create(
        name=f'{username} School', slug=f'{username}-school', admin=user,
    )
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{username}', price=Decimal('89.00'),
        stripe_price_id='price_plan', class_limit=5, student_limit=100,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school, plan, sub


# ---------------------------------------------------------------------------
# 1. A paying school must never be handed a paid module for free in silence
# ---------------------------------------------------------------------------

class UnbilledActivationIsLoudTest(TestCase):
    """ModuleToggleView's local-activation branch is right for one caller and
    wrong for the other. It must be able to tell them apart out loud."""

    def setUp(self):
        self.user, self.school, self.plan, self.sub = _hoi_school()
        ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('10.00'), stripe_price_id='',  # the production state
        )
        self.client.login(username='unbilled_hoi', password='testpass123')

    def _toggle(self):
        return self.client.post(
            reverse('module_toggle'),
            {'module': 'teachers_attendance', 'action': 'add'},
            follow=True,
        )

    def test_paying_school_with_no_stripe_price_is_audited(self):
        self.sub.stripe_subscription_id = 'sub_paying_123'
        self.sub.save(update_fields=['stripe_subscription_id'])

        self._toggle()

        ev = AuditLog.objects.get(action='module_activated_unbilled')
        self.assertEqual(ev.school, self.school)
        self.assertEqual(ev.detail['module'], 'teachers_attendance')

    def test_paying_school_is_told_on_screen(self):
        """The person switching it on is the one who can raise it with support."""
        self.sub.stripe_subscription_id = 'sub_paying_123'
        self.sub.save(update_fields=['stripe_subscription_id'])

        resp = self._toggle()

        text = ' '.join(str(m) for m in resp.context['messages'])
        self.assertIn('will not be billed', text)

    def test_the_module_is_still_switched_on(self):
        """Warning, not refusing. Withholding a feature the head just asked for
        would turn a billing gap into an outage."""
        self.sub.stripe_subscription_id = 'sub_paying_123'
        self.sub.save(update_fields=['stripe_subscription_id'])

        self._toggle()

        self.assertTrue(ModuleSubscription.objects.filter(
            school_subscription=self.sub, module='teachers_attendance',
            is_active=True).exists())

    def test_trialing_school_is_not_warned(self):
        """No Stripe subscription means nothing to bill against. This branch is
        the intended path for a trial, and crying wolf here would train everyone
        to ignore the real case."""
        self.assertEqual(self.sub.stripe_subscription_id, '')

        resp = self._toggle()

        self.assertFalse(AuditLog.objects.filter(
            action='module_activated_unbilled').exists())
        text = ' '.join(str(m) for m in resp.context['messages'])
        self.assertNotIn('will not be billed', text)


# ---------------------------------------------------------------------------
# 2. Modules already given away have to be findable
# ---------------------------------------------------------------------------

class AuditUnbilledModulesCommandTest(TestCase):
    """The view warning only helps the next school. The ones already switched on
    are invisible without asking the question directly."""

    def setUp(self):
        self.user, self.school, self.plan, self.sub = _hoi_school('audit_hoi')
        self.sub.stripe_subscription_id = 'sub_paying_123'
        self.sub.save(update_fields=['stripe_subscription_id'])
        self.product = ModuleProduct.objects.create(
            module='ai_grading_professional', name='AI Grading Professional',
            price=Decimal('49.00'), stripe_price_id='',
        )

    def _run(self, *args):
        out = StringIO()
        call_command('audit_unbilled_modules', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_the_production_case_is_named_with_its_price(self):
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=True, stripe_subscription_item_id='',
        )
        output = self._run()
        self.assertIn('AI Grading Professional', output)
        self.assertIn('audit_hoi School', output)
        self.assertIn('49', output)

    def test_a_billed_module_is_not_reported(self):
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=True, stripe_subscription_item_id='si_real_item',
        )
        self.assertIn('No unbilled modules', self._run())

    def test_a_trialing_school_is_not_reported(self):
        """A school with no Stripe subscription is supposed to hold modules for
        free — reporting it would bury the real cases."""
        SchoolSubscription.objects.filter(pk=self.sub.pk).update(
            stripe_subscription_id='')
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=True, stripe_subscription_item_id='',
        )
        self.assertIn('No unbilled modules', self._run())

    def test_a_switched_off_module_is_not_reported(self):
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=False, stripe_subscription_item_id='',
        )
        self.assertIn('No unbilled modules', self._run())

    def test_a_free_module_is_not_reported(self):
        ModuleProduct.objects.filter(pk=self.product.pk).update(price=Decimal('0'))
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=True, stripe_subscription_item_id='',
        )
        self.assertIn('No unbilled modules', self._run())

    def test_the_total_given_away_is_added_up(self):
        """One line per module is a list; the monthly total is the argument for
        fixing it."""
        ModuleProduct.objects.create(
            module='invoicing', name='Invoicing', price=Decimal('10.00'),
            stripe_price_id='',
        )
        for slug in ('ai_grading_professional', 'invoicing'):
            ModuleSubscription.objects.create(
                school_subscription=self.sub, module=slug, is_active=True,
                stripe_subscription_item_id='',
            )
        output = self._run()
        self.assertIn('59', output)  # 49 + 10

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    def test_verify_stripe_catches_an_item_deleted_in_the_dashboard(self):
        """The reverse drift: billed according to us, gone according to Stripe."""
        import stripe
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=True, stripe_subscription_item_id='si_deleted',
        )
        with patch('stripe.SubscriptionItem.retrieve',
                   side_effect=stripe.error.InvalidRequestError('No such item', None)):
            output = self._run('--verify-stripe')
        self.assertIn('no longer exists', output)

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    def test_a_stripe_outage_is_not_reported_as_a_billing_hole(self):
        import stripe
        ModuleSubscription.objects.create(
            school_subscription=self.sub, module='ai_grading_professional',
            is_active=True, stripe_subscription_item_id='si_real',
        )
        with patch('stripe.SubscriptionItem.retrieve',
                   side_effect=stripe.error.APIConnectionError('network down')):
            output = self._run('--verify-stripe')
        self.assertIn('could not check', output)
        self.assertNotIn('no longer exists', output)


# ---------------------------------------------------------------------------
# 3. The price shown must be the price charged
# ---------------------------------------------------------------------------

@override_settings(STRIPE_SECRET_KEY='sk_test_dummy', STRIPE_CURRENCY='usd')
class PriceAmountDriftTest(TestCase):

    def setUp(self):
        cache.clear()
        self.product = ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('10.00'), stripe_price_id='price_module',
        )

    def tearDown(self):
        cache.clear()

    @patch('stripe.Price.retrieve')
    def test_the_production_drift_is_caught(self, mock_retrieve):
        """$10 in the database, $9 on the invoice — for months."""
        mock_retrieve.return_value = {
            'active': True, 'currency': 'usd', 'unit_amount': 900,
        }
        health = get_stripe_price_health(use_cache=False)
        self.assertEqual(health['status'], 'critical')
        problem = health['broken'][0]['problem']
        self.assertIn('10', problem)
        self.assertIn('9', problem)

    @patch('stripe.Price.retrieve')
    def test_a_matching_amount_is_clean(self, mock_retrieve):
        mock_retrieve.return_value = {
            'active': True, 'currency': 'usd', 'unit_amount': 1000,
        }
        self.assertEqual(get_stripe_price_health(use_cache=False)['status'], 'ok')

    @patch('stripe.Price.retrieve')
    def test_the_fix_says_the_stripe_price_cannot_be_edited(self, mock_retrieve):
        """Anyone sent to the Stripe dashboard to "correct the amount" will not
        find a field to do it in — a Price is immutable."""
        mock_retrieve.return_value = {
            'active': True, 'currency': 'usd', 'unit_amount': 900,
        }
        fix = get_stripe_price_health(use_cache=False)['broken'][0]['fix']
        self.assertIn('cannot be edited', fix)

    @patch('stripe.Price.retrieve')
    def test_a_missing_unit_amount_makes_no_claim(self, mock_retrieve):
        """Tiered prices carry no unit_amount. Absent is not zero — reading it
        as zero would report every tiered price as charging nothing."""
        mock_retrieve.return_value = {'active': True, 'currency': 'usd'}
        self.assertEqual(get_stripe_price_health(use_cache=False)['status'], 'ok')

    @patch('stripe.Price.retrieve')
    def test_an_archived_price_is_reported_once_not_twice(self, mock_retrieve):
        """Archived AND the wrong amount is one thing to fix, not two lines."""
        mock_retrieve.return_value = {
            'active': False, 'currency': 'usd', 'unit_amount': 900,
        }
        broken = get_stripe_price_health(use_cache=False)['broken']
        self.assertEqual(len(broken), 1)
        self.assertIn('Archived in Stripe', broken[0]['problem'])


# ---------------------------------------------------------------------------
# 4. The upsell page a blocked school reads
# ---------------------------------------------------------------------------

class ModuleRequiredPriceTest(TestCase):

    def setUp(self):
        self.user, self.school, self.plan, self.sub = _hoi_school('blocked_hoi')
        ModuleProduct.objects.create(
            module='ai_grading_professional', name='AI Grading Professional',
            price=Decimal('49.00'), stripe_price_id='price_x',
        )
        self.client.login(username='blocked_hoi', password='testpass123')

    def test_the_real_price_is_shown_not_a_literal(self):
        resp = self.client.get(
            reverse('module_required') + '?module=ai_grading_professional')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '49.00')
        self.assertNotContains(resp, '$10/month')

    def test_a_module_with_no_product_row_quotes_no_price(self):
        """Better to say nothing than to invent a number on the screen where
        somebody decides whether to buy."""
        resp = self.client.get(
            reverse('module_required') + '?module=teachers_attendance')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '/month')
