"""Every tier ladder must be buyable, not just enforceable.

This exists because of a regression that shipped. Making `question_automation`
a tier family removed it from the flat module list on the billing page — right,
since three tiers listed as independent switches let a school turn on two at
once — but the page only had hand-written sections for `ai_import` and
`ai_grading`. So the module was gated, priced, synced to Stripe, and had no
button anywhere. A school hit the schedule pages under enforcement, got the
upsell page, and found nothing on it to buy.

The catalogue tests already stop a module being enforceable-but-unpriced.
Nothing stopped it being priced-but-unreachable, which is the same failure one
layer up.
"""

from decimal import Decimal

import pytest
from django.test import TestCase

from billing import registry
from billing.views import BESPOKE_TIER_FAMILIES, _allowance_label
from billing.models import ModuleProduct, ModuleSubscription


# ---------------------------------------------------------------------------
# Declaration — the ladder order lives in the registry
# ---------------------------------------------------------------------------

def test_every_family_is_ranked_weakest_first():
    """A rank of 0 inside a family means the ladder has no defined order."""
    for family, modules in registry.families():
        ranks = [m.tier_rank for m in modules]
        assert 0 not in ranks, (
            f'{family} has an unranked tier: {[m.slug for m in modules]}. '
            'tier_rank must be 1..n so the ladder can be ordered.')
        assert ranks == sorted(ranks), f'{family} came back out of order'
        assert len(set(ranks)) == len(ranks), f'{family} has duplicate ranks'


def test_ordered_members_matches_the_membership_set():
    """The ordered view and the set view must not disagree about who is in."""
    for family, modules in registry.families():
        assert {m.slug for m in modules} == registry.members_of(family)


def test_the_registry_order_matches_the_entitlement_ladders():
    """The resolvers keep their own ordered tuples; they must not drift.

    `strongest_tier` reads those tuples backwards, so a registry rank that
    disagrees would mean the UI offers one order and billing resolves another.
    """
    from billing.entitlements import AI_IMPORT_TIERS, QUESTION_AUTOMATION_TIERS
    from worksheets.grading_service import AI_GRADING_MODULES

    for family, expected in (
        ('ai_import', AI_IMPORT_TIERS),
        ('question_automation', QUESTION_AUTOMATION_TIERS),
        ('ai_grading', tuple(AI_GRADING_MODULES)),
    ):
        got = tuple(m.slug for m in registry.ordered_members_of(family))
        assert got == expected, (
            f'{family}: registry order {got} != resolver ladder {expected}')


def test_bespoke_families_actually_exist():
    """A typo here would silently hide a family from the generic renderer."""
    for family in BESPOKE_TIER_FAMILIES:
        assert registry.members_of(family), (
            f'{family!r} is listed as having a hand-written section but is not '
            'a family in the registry')


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

class EveryLadderIsReachableTest(TestCase):
    """The test the regression needed. Nothing else checks this."""

    @classmethod
    def setUpTestData(cls):
        for module in registry.REGISTRY.values():
            if module.family:
                ModuleProduct.objects.get_or_create(
                    module=module.slug,
                    defaults={'name': module.name, 'price': Decimal('10.00'),
                              'is_active': True},
                )

    def test_every_family_reaches_a_renderer(self):
        """Bespoke block or generic loop — every ladder must reach one.

        Asserted against the TEMPLATE SOURCE, not against the two Python sets.
        Comparing `(all - bespoke) | bespoke` to `all` is a tautology that can
        never fail; the thing that actually broke was a family with no markup,
        so the markup is what has to be checked.
        """
        from django.template.loader import get_template
        source = get_template('billing/institute_dashboard.html').template.source

        # The generic renderer, which covers every non-bespoke family at once.
        assert '{% for fam in tier_families %}' in source, (
            'The generic tier loop is gone from the dashboard. Every family '
            'not in BESPOKE_TIER_FAMILIES has just become unbuyable.')

        # And each family that opted OUT of the generic path must have brought
        # its own markup.
        for family in BESPOKE_TIER_FAMILIES:
            needle = f'{{% for tier in {family}_tiers %}}'
            assert needle in source, (
                f'{family} is in BESPOKE_TIER_FAMILIES — so the generic loop '
                f'skips it — but the dashboard has no "{needle}" block. It is '
                'gated, priced, and has no button.')

    def test_no_tiered_module_is_in_the_flat_module_list(self):
        """The other half: a ladder must not be sold as loose switches.

        Listing tiers flat lets a school add two at once and be billed for both
        while only one takes effect.
        """
        flat = [k for k, _v in ModuleSubscription.MODULE_CHOICES
                if not registry.siblings_of(k)]
        for family, modules in registry.families():
            for module in modules:
                assert module.slug not in flat, (
                    f'{module.slug} is a {family} tier but appears in the flat '
                    'module list')

    def test_question_automation_specifically_is_offered(self):
        """Named outright, because this is the one that broke."""
        assert 'question_automation' not in BESPOKE_TIER_FAMILIES
        tiers = registry.ordered_members_of('question_automation')
        assert len(tiers) == 3
        assert tiers[0].slug.endswith('_starter')
        assert tiers[-1].slug.endswith('_unlimited')


# ---------------------------------------------------------------------------
# Allowance wording
# ---------------------------------------------------------------------------

class AllowanceLabelTest(TestCase):

    def _product(self, **kwargs):
        return ModuleProduct(module='x', name='x', price=Decimal('1'), **kwargs)

    def test_a_schedule_limit_is_worded_as_concurrency(self):
        """"15 schedules at once" — not "15 schedules", which reads as a total.

        The whole point of the limit is that it counts what is running now, so
        the wording has to say so or a school reads it as a lifetime cap.
        """
        assert _allowance_label(self._product(schedules_limit=15)) == \
            '15 schedules at once'

    def test_pages_and_answers_keep_their_own_units(self):
        assert _allowance_label(self._product(pages_per_month=300)) == '300 pages/mo'
        assert _allowance_label(self._product(questions_per_month=1000)) == \
            '1000 answers/mo'

    def test_an_unmetered_tier_says_unlimited(self):
        """A blank there reads as 'unknown', which is worse than saying it."""
        assert _allowance_label(self._product()) == 'unlimited'
