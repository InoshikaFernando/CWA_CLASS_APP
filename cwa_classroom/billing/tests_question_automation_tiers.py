"""Question automation is tiered, and the ways that tiering could go wrong.

Three of these guard mistakes this codebase has already made once:

* **The family fix.** ``module_for_route`` returns the *first* registry entry
  whose namespace or prefix matches, so every ``ai_import`` route resolves to
  ``ai_import_starter``. Comparing that slug straight against a school's
  entitlements denies the schools on higher tiers a page they pay more for.
  Only shadow mode has kept that off production.

* **Tier resolution order.** ``get_ai_grading_tier`` walks its list forwards
  and so answers "starter" for a school holding all three;
  ``check_ai_import_quota`` takes ``.first()`` off an unordered queryset and
  answers arbitrarily. Both would silently under-serve a paying school.

* **What "active" counts.** ``QuestionSchedule.is_active`` is a pause switch,
  not a lifecycle flag — nothing clears it when a term ends. Counting it alone
  makes a school's usage grow forever and locks them out of a limit they never
  actually reached.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import TestCase

from accounts.models import CustomUser
from billing import registry
from billing.catalogue import MODULE_CATALOGUE
from billing.entitlements import (
    QUESTION_AUTOMATION_TIERS, check_schedule_limit, question_automation_tier,
    running_schedule_count,
)
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from classroom.models import ClassRoom, School, Subject
from homework.models import QuestionSchedule

FAMILY = 'question_automation'


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------

def test_every_tier_is_sellable_and_enforceable():
    """A tier missing from any of the three places is half a product."""
    choices = {s for s, _label in ModuleSubscription.MODULE_CHOICES}
    for slug in QUESTION_AUTOMATION_TIERS:
        assert slug in registry.slugs(), f'{slug} missing from the registry'
        assert slug in choices, f'{slug} missing from MODULE_CHOICES'
        assert slug in MODULE_CATALOGUE, f'{slug} missing from the catalogue'


def test_the_retired_untiered_slug_is_gone():
    """`question_automation` is a family name now, not something you can buy.

    Leaving it sellable would let a school hold both it and a tier, and nothing
    would agree on which allowance applied.
    """
    choices = {s for s, _label in ModuleSubscription.MODULE_CHOICES}
    assert FAMILY not in choices
    assert FAMILY not in registry.slugs()
    assert FAMILY not in MODULE_CATALOGUE
    assert ModuleSubscription.FAMILY_QUESTION_AUTOMATION == FAMILY


def test_the_family_holds_exactly_the_three_tiers():
    assert registry.members_of(FAMILY) == set(QUESTION_AUTOMATION_TIERS)


def test_the_catalogue_limits_match_the_tier_names():
    """15 / 75 / unlimited, in that order. A silent edit here reprices the product."""
    assert MODULE_CATALOGUE['question_automation_starter']['schedules_limit'] == 15
    assert MODULE_CATALOGUE['question_automation_professional']['schedules_limit'] == 75
    assert MODULE_CATALOGUE['question_automation_unlimited']['schedules_limit'] is None


# ---------------------------------------------------------------------------
# satisfied_by — the family fix
# ---------------------------------------------------------------------------

def test_any_tier_satisfies_a_route_that_resolves_to_another():
    """The bug this exists to prevent, stated directly.

    A schedule route resolves to whichever tier is listed first. A school on
    Unlimited holds a different slug, and must still be let through.
    """
    resolved = registry.module_for_route('homework', 'schedule_list')
    assert resolved in QUESTION_AUTOMATION_TIERS

    satisfying = registry.satisfied_by(resolved)
    for slug in QUESTION_AUTOMATION_TIERS:
        assert slug in satisfying, (
            f'A school holding {slug} would be denied a route resolving to '
            f'{resolved}. Any tier must open the whole family.')


def test_the_same_holds_for_the_ai_families():
    """ai_import and ai_grading had this bug too; the fix is shared, not special-cased."""
    for family in ('ai_import', 'ai_grading'):
        members = registry.members_of(family)
        assert len(members) == 3, f'{family} should have three tiers'
        for slug in members:
            assert registry.satisfied_by(slug) == members


def test_a_standalone_module_is_satisfied_only_by_itself():
    """The family logic must not quietly widen a single-slug requirement."""
    assert registry.satisfied_by('invoicing') == frozenset({'invoicing'})
    assert registry.satisfied_by('student_progress_reports') == frozenset(
        {'student_progress_reports'})


def test_an_unknown_requirement_denies_rather_than_allows():
    """A slug nobody declared must not resolve to an empty set.

    An empty set intersects nothing, which reads as "denied" at the middleware
    — but a caller doing `slug in satisfied_by(...)` would get False either
    way. Returning the slug itself keeps the failure loud and local.
    """
    assert registry.satisfied_by('no_such_module') == frozenset({'no_such_module'})
    assert registry.satisfied_by(None) == frozenset()
    assert registry.satisfied_by('') == frozenset()


# ---------------------------------------------------------------------------
# Resolution and counting, against real rows
# ---------------------------------------------------------------------------

class TierResolutionTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        admin = CustomUser.objects.create_user('qa_admin', 'qa@test.com', 'pass1234')
        cls.school = School.objects.create(
            name='Tier School', slug='tier-school', admin=admin)
        cls.subscription = SchoolSubscription.objects.create(
            school=cls.school,
            plan=InstitutePlan.objects.create(
                name='Standard', slug='qa-standard', price=Decimal('99.00'),
                class_limit=0, student_limit=0, invoice_limit_yearly=100,
                extra_invoice_rate=Decimal('0.50'),
            ),
            status=SchoolSubscription.STATUS_ACTIVE,
        )
        cls.subject = Subject.objects.create(name='Maths', slug='qa-maths')
        cls.classroom = ClassRoom.objects.create(
            name='Tier Class', code='TIER0001', school=cls.school,
            subject=cls.subject,
        )
        for slug, limit in (
            ('question_automation_starter', 15),
            ('question_automation_professional', 75),
            ('question_automation_unlimited', None),
        ):
            ModuleProduct.objects.get_or_create(
                module=slug,
                defaults={'name': slug, 'price': Decimal('10.00'),
                          'schedules_limit': limit, 'is_active': True},
            )

    def _grant(self, slug):
        return ModuleSubscription.objects.create(
            school_subscription=self.subscription, module=slug, is_active=True)

    def _schedule(self, *, start_offset, end_offset, is_active=True, name='Plan'):
        today = date.today()
        return QuestionSchedule.objects.create(
            classroom=self.classroom, name=name,
            scope=QuestionSchedule.SCOPE_CUSTOM,
            start_date=today + timedelta(days=start_offset),
            end_date=today + timedelta(days=end_offset),
            is_active=is_active,
        )

    # -- tier resolution -------------------------------------------------

    def test_no_tier_resolves_to_none(self):
        assert question_automation_tier(self.school) is None

    def test_a_single_tier_resolves_to_itself(self):
        self._grant('question_automation_professional')
        assert question_automation_tier(self.school) == 'question_automation_professional'

    def test_holding_several_tiers_resolves_to_the_strongest(self):
        """The trap the AI families fall into, pinned so this one cannot.

        A school that upgrades without the old row being deactivated must not
        be served the weaker allowance it used to pay for.
        """
        self._grant('question_automation_starter')
        self._grant('question_automation_unlimited')
        assert question_automation_tier(self.school) == 'question_automation_unlimited'

    def test_an_inactive_tier_row_does_not_count(self):
        self._grant('question_automation_unlimited').delete()
        row = self._grant('question_automation_starter')
        ModuleSubscription.objects.create(
            school_subscription=self.subscription,
            module='question_automation_unlimited', is_active=False,
        )
        assert question_automation_tier(self.school) == row.module

    # -- what counts as running ------------------------------------------

    def test_a_schedule_whose_window_covers_today_counts(self):
        self._schedule(start_offset=-7, end_offset=60)
        assert running_schedule_count(self.school) == 1

    def test_a_finished_schedule_does_not_count_even_though_it_is_active(self):
        """The accumulation trap, stated as a test.

        Nothing clears is_active when a term ends. If this ever counts, a
        school creating one plan per class per term is locked out within a
        year for usage it does not have.
        """
        finished = self._schedule(start_offset=-200, end_offset=-100, name='Last term')
        assert finished.is_active is True
        assert running_schedule_count(self.school) == 0

    def test_a_future_schedule_does_not_count_yet(self):
        self._schedule(start_offset=30, end_offset=120, name='Next term')
        assert running_schedule_count(self.school) == 0

    def test_a_paused_schedule_does_not_count(self):
        self._schedule(start_offset=-7, end_offset=60, is_active=False)
        assert running_schedule_count(self.school) == 0

    def test_counting_on_a_future_date_sees_that_terms_schedules(self):
        """Creation is checked at the new plan's start date, so this must work."""
        self._schedule(start_offset=30, end_offset=120, name='Next term')
        assert running_schedule_count(self.school) == 0
        assert running_schedule_count(
            self.school, on_date=date.today() + timedelta(days=45)) == 1

    # -- the limit -------------------------------------------------------

    def test_no_tier_is_never_within_limit(self):
        within, current, limit = check_schedule_limit(self.school)
        assert within is False
        assert limit == 0

    def test_unlimited_reports_no_limit(self):
        self._grant('question_automation_unlimited')
        for i in range(20):
            self._schedule(start_offset=-1, end_offset=60, name=f'P{i}')
        within, current, limit = check_schedule_limit(self.school)
        assert within is True
        assert limit is None
        assert current == 20

    def test_starter_allows_up_to_fifteen_running(self):
        self._grant('question_automation_starter')
        for i in range(14):
            self._schedule(start_offset=-1, end_offset=60, name=f'P{i}')
        within, current, limit = check_schedule_limit(self.school)
        assert (within, current, limit) == (True, 14, 15)

    def test_starter_refuses_the_sixteenth(self):
        self._grant('question_automation_starter')
        for i in range(15):
            self._schedule(start_offset=-1, end_offset=60, name=f'P{i}')
        within, current, limit = check_schedule_limit(self.school)
        assert (within, current, limit) == (False, 15, 15)

    def test_last_terms_schedules_do_not_eat_this_terms_allowance(self):
        """The whole reason the date window is in the definition.

        Fifteen finished plans plus one running one is a school using one
        schedule, not sixteen.
        """
        self._grant('question_automation_starter')
        for i in range(15):
            self._schedule(start_offset=-200, end_offset=-100, name=f'Old{i}')
        self._schedule(start_offset=-1, end_offset=60, name='Current')
        within, current, limit = check_schedule_limit(self.school)
        assert (within, current, limit) == (True, 1, 15)

    def test_a_missing_product_row_allows_rather_than_blocks(self):
        """A seeding gap must not stop a school that has paid."""
        self._grant('question_automation_professional')
        ModuleProduct.objects.filter(
            module='question_automation_professional').delete()
        within, current, limit = check_schedule_limit(self.school)
        assert within is True
        assert limit is None
