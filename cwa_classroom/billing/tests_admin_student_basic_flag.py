"""The superuser ticks Student Basic on the code as they create it.

The flag is only useful if the person issuing the code can set it where they
issue it. Two creation surfaces do that — the unified coupon form and the
standalone promo-code form — and both must refuse the one combination that
would quietly sell somebody a reduced product: a code that still charges.

The model refuses it too (``StudentBasicGrantMixin``). These pin the layer the
superuser actually touches, so they are told on the form instead of by a 500.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.models import DiscountCode, Package, PromoCode

User = get_user_model()


class CouponFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='super', password='pass1234', email='super@test.com')
        Package.objects.get_or_create(
            name='Wizard', defaults={'price': 19.90,
                                     'stripe_price_id': 'price_w'})

    def setUp(self):
        self.client.force_login(self.admin)

    URL = '/admin-dashboard/billing/coupon-codes/create/'

    def _post(self, **overrides):
        payload = {
            'target_type': 'student_discount',
            'code': 'PROMO2026',
            'discount_percent': '100',
            'duration': 'forever',
        }
        payload.update(overrides)
        return self.client.post(self.URL, payload)

    # -- the form is reachable and carries the control -------------------

    def test_the_form_offers_the_tick(self):
        response = self.client.get(self.URL)
        self.assertContains(response, 'grants_student_basic')
        self.assertContains(response, 'Student Basic')

    # -- creating a flagged code -----------------------------------------

    def test_a_ticked_free_discount_code_carries_the_tier(self):
        self._post(grants_student_basic='1')
        self.assertTrue(
            DiscountCode.objects.get(code='PROMO2026').grants_student_basic)

    def test_an_unticked_code_does_not(self):
        self._post()
        self.assertFalse(
            DiscountCode.objects.get(code='PROMO2026').grants_student_basic)

    def test_a_ticked_free_promo_code_carries_the_tier(self):
        self._post(target_type='student_promo', code='PROMOP',
                   grants_student_basic='1', class_limit='0')
        self.assertTrue(
            PromoCode.objects.get(code='PROMOP').grants_student_basic)

    # -- the combinations the form must refuse ---------------------------

    def test_it_refuses_a_ticked_partial_discount_code(self):
        response = self._post(discount_percent='50',
                              grants_student_basic='1')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DiscountCode.objects.filter(code='PROMO2026').exists())
        self.assertContains(response, 'Only a 100% off code')

    def test_it_refuses_a_ticked_institute_code(self):
        """Student Basic is a student tier; an institute has no such thing."""
        response = self._post(target_type='institute', code='INST1',
                              grants_student_basic='1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not institutes')

    def test_a_partial_code_is_still_created_when_the_box_is_left_alone(self):
        self._post(discount_percent='50')
        self.assertTrue(DiscountCode.objects.filter(code='PROMO2026').exists())

    # -- it is visible afterwards ----------------------------------------

    def test_the_list_marks_which_codes_carry_it(self):
        self._post(grants_student_basic='1')
        DiscountCode.objects.create(code='PLAINFREE', discount_percent=100)
        response = self.client.get('/admin-dashboard/billing/coupon-codes/')
        self.assertContains(response, 'PROMO2026')
        self.assertContains(response, 'PLAINFREE')
        # One badge, for the one code that carries the tier.
        self.assertEqual(response.content.decode().count('>\n                  Student Basic\n                <'), 1)

    def test_it_is_recorded_in_the_audit_log(self):
        from audit.models import AuditLog

        self._post(grants_student_basic='1')
        entry = AuditLog.objects.filter(action='coupon_code_created').first()
        self.assertTrue(entry.detail['grants_student_basic'])


class StandalonePromoFormTests(TestCase):
    """The other creation surface — same rules."""

    URL = '/admin-dashboard/billing/promo-codes/create/'

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='super2', password='pass1234', email='super2@test.com')
        self.client.force_login(self.admin)

    def test_the_form_offers_the_tick(self):
        self.assertContains(self.client.get(self.URL), 'grants_student_basic')

    def test_a_ticked_free_code_carries_the_tier(self):
        self.client.post(self.URL, {
            'code': 'FREEP', 'discount_percent': '100', 'class_limit': '0'
        } | {'grants_student_basic': '1'})
        self.assertTrue(PromoCode.objects.get(code='FREEP').grants_student_basic)

    def test_it_refuses_a_ticked_partial_code(self):
        response = self.client.post(self.URL, {
            'code': 'HALFP', 'discount_percent': '40', 'class_limit': '0',
            'grants_student_basic': '1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PromoCode.objects.filter(code='HALFP').exists())
        self.assertContains(response, 'Only a 100% off code')
