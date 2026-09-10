"""The AI Question Import tier ladder, and the two pages that quote it.

Both pages used to carry their own hard-coded copy of the table, and both
copies were wrong: the plans page advertised $15/mo for Starter under a "50%
off your first year" banner whose own small print said "6 months", while the
Stripe price the school is actually charged — ``ModuleProduct.stripe_price_id``,
synced from the catalogue — was $29.

So these tests pin the two things that fixed it: the advertised price is read
from the catalogue Stripe is synced against, and the introductory offer is only
stated when billing applies it.
"""
import re
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing import ai_tiers
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from classroom.models import School, SchoolTeacher


def _catalogue(**overrides):
    """The three AI import tiers at their production prices."""
    rows = [
        ('ai_import_starter', 'AI Question Import - Starter', 300, '29.00'),
        ('ai_import_professional', 'AI Question Import - Professional', 600, '59.00'),
        ('ai_import_enterprise', 'AI Question Import - Enterprise', 1000, '99.00'),
    ]
    for slug, name, pages, price in rows:
        defaults = {
            'name': name, 'pages_per_month': pages, 'price': Decimal(price),
            'is_active': True, 'stripe_price_id': f'price_{slug}',
        }
        defaults.update(overrides.get(slug, {}))
        ModuleProduct.objects.update_or_create(module=slug, defaults=defaults)


class TierTableTests(TestCase):

    def test_the_advertised_price_is_the_price_stripe_will_charge(self):
        """The bug, in one assertion.

        The page said $15 for Starter. Stripe's price, from this same
        catalogue row, was $29. Whatever the row says is what the page says.
        """
        _catalogue()
        by_slug = {t['slug']: t for t in ai_tiers.ai_import_tiers()}

        self.assertEqual(by_slug['ai_import_starter']['price'], Decimal('29.00'))
        self.assertEqual(by_slug['ai_import_professional']['price'], Decimal('59.00'))
        self.assertEqual(by_slug['ai_import_enterprise']['price'], Decimal('99.00'))

    def test_a_price_change_in_the_catalogue_moves_the_page(self):
        _catalogue(ai_import_starter={'price': Decimal('35.00')})
        starter = ai_tiers.ai_import_tiers()[0]
        self.assertEqual(starter['price'], Decimal('35.00'))
        self.assertEqual(starter['intro_price'], Decimal('17.50'))

    def test_pages_come_from_the_row_that_enforces_the_quota(self):
        """Advertising 600 pages while metering 300 would be its own bug."""
        _catalogue(ai_import_professional={'pages_per_month': 750})
        tiers = {t['slug']: t for t in ai_tiers.ai_import_tiers()}
        self.assertEqual(tiers['ai_import_professional']['pages'], 750)

    def test_a_tier_with_no_stripe_price_is_not_offered(self):
        """ModuleToggleView falls through to free local activation without one,
        so advertising it sells a module for nothing."""
        _catalogue(ai_import_enterprise={'stripe_price_id': ''})
        slugs = [t['slug'] for t in ai_tiers.ai_import_tiers()]
        self.assertNotIn('ai_import_enterprise', slugs)
        self.assertEqual(len(slugs), 2)

    def test_a_deactivated_tier_is_not_offered(self):
        _catalogue(ai_import_starter={'is_active': False})
        self.assertNotIn('ai_import_starter',
                         [t['slug'] for t in ai_tiers.ai_import_tiers()])

    def test_an_empty_catalogue_offers_nothing_rather_than_a_default(self):
        self.assertEqual(ai_tiers.ai_import_tiers(), [])

    def test_the_ladder_climbs(self):
        _catalogue()
        tiers = ai_tiers.ai_import_tiers()
        self.assertEqual([t['pages'] for t in tiers],
                         sorted(t['pages'] for t in tiers))
        self.assertEqual([t['price'] for t in tiers],
                         sorted(t['price'] for t in tiers))

    def test_current_tier_is_marked(self):
        _catalogue()
        tiers = ai_tiers.ai_import_tiers('ai_import_professional')
        self.assertEqual([t['slug'] for t in tiers if t['is_current']],
                         ['ai_import_professional'])
        self.assertEqual([t['is_current'] for t in ai_tiers.ai_import_tiers()],
                         [False, False, False])

    def test_the_intro_price_is_the_advertised_percentage_off(self):
        _catalogue()
        for tier in ai_tiers.ai_import_tiers():
            factor = Decimal(100 - ai_tiers.INTRO_DISCOUNT_PERCENT) / Decimal(100)
            self.assertEqual(tier['intro_price'],
                             (tier['price'] * factor).quantize(Decimal('0.01')))


class DiscountCopyTests(TestCase):
    """The offer is stated once, in code — not typed into templates."""

    TEMPLATES = [
        'templates/ai_import/tier_select.html',
        'templates/billing/institute_dashboard.html',
    ]

    def _template_text(self, path):
        from django.conf import settings
        return (settings.BASE_DIR / path).read_text()

    def _without_template_syntax(self, text):
        """Strip {{ vars }} and {% comment %} blocks — those are not the copy."""
        text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '',
                      text, flags=re.DOTALL)
        return re.sub(r'\{\{.*?\}\}', '', text, flags=re.DOTALL)

    def test_no_template_hard_codes_a_discount_duration(self):
        """This is the exact bug: "first year" in the banner, "6 months" below.

        A literal duration is one the constant cannot correct, so the two can
        disagree again the moment either changes.
        """
        literal = re.compile(
            r'(first year|first \d+ months?|after \d+ months?|\d+ months?\b)',
            re.IGNORECASE,
        )
        for path in self.TEMPLATES:
            found = literal.findall(self._without_template_syntax(
                self._template_text(path)))
            self.assertEqual(
                found, [],
                f'{path} states the discount duration in its own words: '
                f'{found}. Use the ai_discount_* context values instead.',
            )

    def test_no_template_hard_codes_a_tier_price(self):
        """A price typed into a page is one the catalogue cannot correct — and
        the catalogue is what Stripe charges from."""
        _catalogue()
        for path in self.TEMPLATES:
            text = self._without_template_syntax(self._template_text(path))
            for tier in ai_tiers.ai_import_tiers():
                for amount in (tier['price'], tier['intro_price']):
                    for rendered in (f'${amount}', f'${int(amount)}'):
                        self.assertNotIn(
                            rendered, text,
                            f'{path} hard-codes {rendered} for {tier["name"]}',
                        )


class RenderedPagesTests(TestCase):
    """Rendered, not just imported — the templates must read the right keys."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_user(
            'hoi', 'hoi@test.internal', 'pw1!',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        UserRole.objects.create(user=cls.owner, role=role)
        cls.school = School.objects.create(
            name='Wizards Academy', slug='wizards', admin=cls.owner, is_active=True,
        )
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.owner,
            defaults={'role': 'teacher', 'is_active': True},
        )
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic', price=Decimal('89.00'), class_limit=5,
            student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        cls.subscription = SchoolSubscription.objects.create(
            school=cls.school, plan=plan, status='active',
        )

    def setUp(self):
        _catalogue()
        self.client.force_login(self.owner)

    def _pages(self):
        plans = self.client.get(reverse('ai_import:tier_select'))
        dashboard = self.client.get(reverse('institute_subscription_dashboard'))
        self.assertEqual(plans.status_code, 200)
        self.assertEqual(dashboard.status_code, 200)
        return (('plans', plans.content.decode()),
                ('dashboard', dashboard.content.decode()))

    def test_both_pages_quote_the_price_that_will_be_charged(self):
        for label, body in self._pages():
            self.assertIn('$29.00', body, label)
            self.assertIn('$59.00', body, label)
            self.assertIn('$99.00', body, label)

    def test_neither_page_advertises_a_discount_that_billing_does_not_apply(self):
        """Nothing in the add-module path applies a coupon, so nothing on the
        page may promise one."""
        self.assertFalse(
            ai_tiers.INTRO_DISCOUNT_ENABLED,
            'Turning the offer on needs the Stripe coupon wired first — see '
            'billing/ai_tiers.py.',
        )
        for label, body in self._pages():
            self.assertNotIn('% off', body, label)
            self.assertNotIn('first year', body, label)
            self.assertNotIn('6 months', body, label)
            # And the half-price numbers are nowhere on the page either.
            self.assertNotIn('$14.50', body, label)
            self.assertNotIn('$29.50', body, label)

    def test_with_the_offer_on_both_pages_state_the_same_thing(self):
        """What the page becomes once the coupon exists."""
        with mock.patch.object(ai_tiers, 'INTRO_DISCOUNT_ENABLED', True):
            pages = self._pages()

        for label, body in pages:
            self.assertIn('$14.50', body, label)   # half of $29
            self.assertIn('first year', body, label)
            # The full price is still shown — it is what they pay from month 13.
            self.assertIn('$29.00', body, label)
            self.assertNotIn('6 months', body, label)

        plans = dict(pages)['plans']
        self.assertIn(f'{ai_tiers.INTRO_DISCOUNT_PERCENT}% off', plans)
        self.assertIn(f'after {ai_tiers.INTRO_DISCOUNT_MONTHS} months', plans)

    def test_the_dashboard_still_marks_the_active_tier(self):
        ModuleSubscription.objects.create(
            school_subscription=self.subscription,
            module='ai_import_professional', is_active=True,
        )
        body = dict(self._pages())['dashboard']
        self.assertIn('ai_import_professional', body)
