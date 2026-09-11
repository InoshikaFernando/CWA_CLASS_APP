"""A school holding two tiers of one ladder must get the one it pays most for.

It is not supposed to hold two. The add path retires the sibling and
``grant_module`` now does the same. But an upgrade that fails between adding
the new Stripe item and removing the old, a webhook arriving out of order, or a
grant landing beside an existing row all leave two active rows, and
``unique_together`` is per (subscription, module) so the database permits it.

Both resolvers used to answer wrongly in that state, and neither raised:

* ``get_ai_grading_tier`` walked ``AI_GRADING_MODULES`` forwards and returned
  the first match, so Starter + Enterprise resolved to **Starter** — 1,000
  answers a month instead of unlimited.
* ``check_ai_import_quota`` took ``.first()`` off a queryset with no
  ``order_by``, so the page quota was whatever the database returned.

The school was simply served less than it bought and ran out early. These tests
pin the fix at both ends: the strongest tier wins at read time, and the write
paths stop two rows existing in the first place.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.models import CustomUser
from billing import registry
from billing.entitlements import (
    AI_IMPORT_TIERS, ai_import_tier, check_ai_import_quota,
    deactivate_sibling_modules, strongest_tier,
)
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from classroom.models import School
from worksheets.grading_service import AI_GRADING_MODULES, get_ai_grading_tier


class _LadderCase(TestCase):
    """A school with a subscription and every tier product seeded."""

    @classmethod
    def setUpTestData(cls):
        admin = CustomUser.objects.create_user(
            'ladder_admin', 'ladder@test.com', 'pass1234')
        cls.school = School.objects.create(
            name='Ladder School', slug='ladder-school', admin=admin)
        cls.subscription = SchoolSubscription.objects.create(
            school=cls.school,
            plan=InstitutePlan.objects.create(
                name='Standard', slug='ladder-standard', price=Decimal('99.00'),
                class_limit=0, student_limit=0, invoice_limit_yearly=100,
                extra_invoice_rate=Decimal('0.50'),
            ),
            status=SchoolSubscription.STATUS_ACTIVE,
        )
        for slug, pages in (
            ('ai_import_starter', 300),
            ('ai_import_professional', 600),
            ('ai_import_enterprise', 1000),
        ):
            ModuleProduct.objects.update_or_create(
                module=slug,
                defaults={'name': slug, 'price': Decimal('30.00'),
                          'pages_per_month': pages, 'is_active': True},
            )
        for slug, questions in (
            ('ai_grading_starter', 1000),
            ('ai_grading_professional', 5000),
            ('ai_grading_enterprise', None),
        ):
            ModuleProduct.objects.update_or_create(
                module=slug,
                defaults={'name': slug, 'price': Decimal('15.00'),
                          'questions_per_month': questions, 'is_active': True},
            )

    def _grant(self, slug, *, is_active=True):
        return ModuleSubscription.objects.create(
            school_subscription=self.subscription, module=slug,
            is_active=is_active,
        )


class AiGradingTierTest(_LadderCase):

    def test_no_tier_resolves_to_none(self):
        self.assertIsNone(get_ai_grading_tier(self.school))

    def test_a_single_tier_resolves_to_itself(self):
        self._grant('ai_grading_professional')
        self.assertEqual(
            get_ai_grading_tier(self.school), 'ai_grading_professional')

    def test_starter_beside_enterprise_resolves_to_enterprise(self):
        """The reported bug, stated exactly.

        Before the fix this returned 'ai_grading_starter' — the school was
        capped at 1,000 answers a month while paying for unlimited.
        """
        self._grant('ai_grading_starter')
        self._grant('ai_grading_enterprise')
        self.assertEqual(
            get_ai_grading_tier(self.school), 'ai_grading_enterprise')

    def test_all_three_resolves_to_enterprise(self):
        for slug in AI_GRADING_MODULES:
            self._grant(slug)
        self.assertEqual(
            get_ai_grading_tier(self.school), 'ai_grading_enterprise')

    def test_an_inactive_stronger_row_does_not_win(self):
        """Cancelled is cancelled — only active rows count."""
        self._grant('ai_grading_starter')
        self._grant('ai_grading_enterprise', is_active=False)
        self.assertEqual(
            get_ai_grading_tier(self.school), 'ai_grading_starter')


class AiImportQuotaTest(_LadderCase):

    def test_a_single_tier_gives_its_own_quota(self):
        self._grant('ai_import_starter')
        _remaining, limit, _used = check_ai_import_quota(self.school)
        self.assertEqual(limit, 300)

    def test_starter_beside_enterprise_gives_the_enterprise_quota(self):
        """`.first()` on an unordered queryset used to decide this arbitrarily."""
        self._grant('ai_import_starter')
        self._grant('ai_import_enterprise')
        _remaining, limit, _used = check_ai_import_quota(self.school)
        self.assertEqual(limit, 1000)

    def test_the_resolver_and_the_quota_agree(self):
        self._grant('ai_import_professional')
        self._grant('ai_import_starter')
        self.assertEqual(ai_import_tier(self.school), 'ai_import_professional')
        _remaining, limit, _used = check_ai_import_quota(self.school)
        self.assertEqual(limit, 600)

    def test_no_tier_gives_no_quota(self):
        self.assertEqual(check_ai_import_quota(self.school), (0, 0, 0))


class StrongestTierTest(_LadderCase):
    """The shared helper, since three ladders now depend on it."""

    def test_order_is_read_backwards_not_forwards(self):
        self._grant('ai_import_starter')
        self._grant('ai_import_professional')
        self.assertEqual(
            strongest_tier(self.subscription, AI_IMPORT_TIERS),
            'ai_import_professional')

    def test_a_subscription_of_none_resolves_to_none(self):
        """A school with no subscription must not raise on the way to a denial."""
        self.assertIsNone(strongest_tier(None, AI_IMPORT_TIERS))

    def test_rows_outside_the_ladder_are_ignored(self):
        self._grant('invoicing')
        self.assertIsNone(strongest_tier(self.subscription, AI_IMPORT_TIERS))


class SiblingRetirementTest(_LadderCase):
    """Stop two rows existing, rather than only resolving them afterwards."""

    def test_granting_a_tier_retires_its_siblings(self):
        self._grant('ai_grading_starter')
        retired = deactivate_sibling_modules(
            self.subscription, 'ai_grading_enterprise')
        self.assertEqual(retired, frozenset({'ai_grading_starter'}))
        self.assertFalse(
            ModuleSubscription.objects.get(
                school_subscription=self.subscription,
                module='ai_grading_starter').is_active)

    def test_it_is_a_no_op_for_a_module_that_stands_alone(self):
        self._grant('invoicing')
        self.assertEqual(
            deactivate_sibling_modules(self.subscription, 'invoicing'),
            frozenset())
        self.assertTrue(
            ModuleSubscription.objects.get(
                school_subscription=self.subscription,
                module='invoicing').is_active)

    def test_it_does_not_touch_another_family(self):
        self._grant('ai_import_starter')
        deactivate_sibling_modules(self.subscription, 'ai_grading_enterprise')
        self.assertTrue(
            ModuleSubscription.objects.get(
                school_subscription=self.subscription,
                module='ai_import_starter').is_active)

    def test_grant_module_retires_the_weaker_tier(self):
        """The path that had no exclusivity at all.

        `grant_module` is how a comped school is set up, so granting a top tier
        to a school already on a lower one is exactly the case that produced
        two rows.
        """
        self._grant('ai_grading_starter')
        call_command('grant_module', 'ai_grading_enterprise',
                     '--school', str(self.school.pk), '--reason', 'test')

        self.assertEqual(
            get_ai_grading_tier(self.school), 'ai_grading_enterprise')
        self.assertFalse(
            ModuleSubscription.objects.get(
                school_subscription=self.subscription,
                module='ai_grading_starter').is_active)


class LadderDeclarationTest(TestCase):
    """The registry is now the only place a ladder is declared."""

    def test_every_known_ladder_has_three_tiers(self):
        for family in ('ai_import', 'ai_grading', 'question_automation'):
            self.assertEqual(
                len(registry.members_of(family)), 3,
                f'{family} should declare three tiers')

    def test_the_grading_list_matches_the_registry(self):
        """worksheets keeps its own ordered list; it must not drift from the family."""
        self.assertEqual(
            set(AI_GRADING_MODULES), registry.members_of('ai_grading'))

    def test_the_import_list_matches_the_registry(self):
        self.assertEqual(set(AI_IMPORT_TIERS), registry.members_of('ai_import'))

    def test_a_tiered_module_is_never_offered_as_a_standalone_switch(self):
        """The billing page lists modules a school can just switch on.

        A ladder listed there lets a school add two tiers at once and be billed
        for both while one takes effect — the bug the exclusivity code was
        written for. Asking the registry means a new ladder cannot reappear
        there by being forgotten.
        """
        standalone = [
            k for k, _v in ModuleSubscription.MODULE_CHOICES
            if not registry.siblings_of(k)
        ]
        for family in ('ai_import', 'ai_grading', 'question_automation'):
            for slug in registry.members_of(family):
                self.assertNotIn(slug, standalone)
