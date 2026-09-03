"""The shared monthly AI page budget (billing/page_quota.py).

Covers what the old ai_import-only counter got wrong: who is metered, when the
75% warning turns on, that an over-budget upload is refused with an upgrade
named, and that pages are charged and refunded correctly.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser
from ai_import.models import AIImportUsage
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from billing import page_quota
from classroom.models import School


def _school(name, slug, *, module='ai_import_professional', pages=600, used=0,
            with_subscription=True):
    admin = CustomUser.objects.create_user(
        f'{slug}-admin', f'{slug}@test.internal', 'pw1!')
    school = School.objects.create(name=name, slug=slug, admin=admin, is_active=True)
    if not with_subscription:
        return school

    plan = InstitutePlan.objects.create(
        name=f'{name} Plan', slug=f'{slug}-plan', price=Decimal('89.00'),
        class_limit=5, student_limit=100, invoice_limit_yearly=500,
        extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status='active',
        current_period_start=timezone.now(),
        current_period_end=timezone.now() + timezone.timedelta(days=30),
    )
    if module:
        ModuleProduct.objects.update_or_create(
            module=module,
            defaults={'name': f'AI Import - {module}', 'price': Decimal('30.00'),
                      'pages_per_month': pages},
        )
        ModuleSubscription.objects.create(
            school_subscription=sub, module=module, is_active=True,
        )
    if used:
        AIImportUsage.objects.create(
            school=school, period_start=page_quota.current_period_start(),
            pages_processed=used, tokens_used=0,
        )
    return school


def _seed_ladder():
    """The three tiers, so 'the next one up' has something to find."""
    for slug, pages, price in [
        ('ai_import_starter', 300, '15.00'),
        ('ai_import_professional', 600, '30.00'),
        ('ai_import_enterprise', 1000, '50.00'),
    ]:
        ModuleProduct.objects.update_or_create(
            module=slug,
            defaults={'name': f'AI Import - {slug.rsplit("_", 1)[-1].title()}',
                      'price': Decimal(price), 'pages_per_month': pages,
                      'is_active': True},
        )


class WhoIsMeteredTests(TestCase):
    """The allowance IS the AI import tier — a school without one is unmetered."""

    def test_school_without_subscription_is_not_metered(self):
        school = _school('No Sub', 'no-sub', with_subscription=False)
        status = page_quota.quota_status(school)
        self.assertFalse(status['metered'])
        self.assertTrue(page_quota.check_page_budget(school, 5_000)[0])

    def test_school_without_ai_module_is_not_metered(self):
        school = _school('No AI', 'no-ai', module=None)
        status = page_quota.quota_status(school)
        self.assertFalse(status['metered'])
        self.assertEqual(status['reason'], 'no_ai_module')
        self.assertTrue(page_quota.check_page_budget(school, 5_000)[0])

    def test_no_school_is_not_metered(self):
        self.assertFalse(page_quota.quota_status(None)['metered'])

    def test_superuser_is_not_metered(self):
        school = _school('Super', 'super', pages=600, used=600)
        status = page_quota.quota_status(school, unlimited=True)
        self.assertFalse(status['metered'])
        self.assertTrue(page_quota.check_page_budget(school, 900, unlimited=True)[0])

    def test_tier_with_zero_pages_is_unlimited(self):
        school = _school('Unlimited', 'unlimited-tier', pages=0)
        self.assertFalse(page_quota.quota_status(school)['metered'])


class QuotaStatusTests(TestCase):
    def test_fresh_allowance_reports_full_remaining(self):
        school = _school('Fresh', 'fresh', pages=600)
        status = page_quota.quota_status(school)
        self.assertTrue(status['metered'])
        self.assertEqual((status['used'], status['limit'], status['remaining']), (0, 600, 600))
        self.assertEqual(status['percent'], 0)
        self.assertFalse(status['warn'])
        self.assertFalse(status['exhausted'])
        self.assertEqual(status['tier_name'], 'Professional')

    def test_warning_starts_at_75_percent_not_before(self):
        just_under = _school('Under', 'under', pages=600, used=449)   # 74.8%
        self.assertFalse(page_quota.quota_status(just_under)['warn'])

        at_threshold = _school('At75', 'at-75', pages=600, used=450)  # exactly 75%
        status = page_quota.quota_status(at_threshold)
        self.assertTrue(status['warn'])
        self.assertEqual(status['percent'], 75)

    def test_warning_persists_above_the_threshold(self):
        school = _school('High', 'high', pages=600, used=560)
        status = page_quota.quota_status(school)
        self.assertTrue(status['warn'])
        self.assertFalse(status['exhausted'])

    def test_exhausted_replaces_the_warning(self):
        school = _school('Spent', 'spent', pages=600, used=600)
        status = page_quota.quota_status(school)
        self.assertTrue(status['exhausted'])
        self.assertFalse(status['warn'])
        self.assertEqual(status['remaining'], 0)
        self.assertEqual(status['percent'], 100)

    def test_overspend_does_not_report_negative_or_over_100(self):
        school = _school('Over', 'over', pages=600, used=962)
        status = page_quota.quota_status(school)
        self.assertEqual(status['remaining'], 0)
        self.assertEqual(status['percent'], 100)

    def test_next_tier_is_the_cheapest_bigger_one(self):
        _seed_ladder()
        school = _school('Ladder', 'ladder', pages=600, used=0)
        self.assertEqual(page_quota.quota_status(school)['next_tier_name'], 'Enterprise')
        self.assertEqual(page_quota.quota_status(school)['next_tier_pages'], 1000)

    def test_top_tier_has_no_upgrade_to_offer(self):
        _seed_ladder()
        school = _school('Top', 'top', module='ai_import_enterprise', pages=1000)
        self.assertEqual(page_quota.quota_status(school)['next_tier_name'], '')


class CheckPageBudgetTests(TestCase):
    def test_upload_within_the_allowance_is_allowed(self):
        school = _school('Fits', 'fits', pages=600, used=100)
        allowed, message, _ = page_quota.check_page_budget(school, 40)
        self.assertTrue(allowed)
        self.assertIsNone(message)

    def test_upload_larger_than_whats_left_is_refused(self):
        _seed_ladder()
        school = _school('Tight', 'tight', pages=600, used=580)
        allowed, message, _ = page_quota.check_page_budget(school, 40)
        self.assertFalse(allowed)
        self.assertIn('20', message)          # what is left
        self.assertIn('Enterprise', message)  # the way out
        self.assertIn('1,000 pages', message)

    def test_exhausted_allowance_names_the_upgrade(self):
        _seed_ladder()
        school = _school('Done', 'done', pages=600, used=600)
        allowed, message, _ = page_quota.check_page_budget(school, 1)
        self.assertFalse(allowed)
        self.assertIn('used all 600 pages', message)
        self.assertIn('Enterprise', message)

    def test_exactly_the_remaining_pages_is_allowed(self):
        school = _school('Exact', 'exact', pages=600, used=580)
        self.assertTrue(page_quota.check_page_budget(school, 20)[0])

    def test_top_tier_message_does_not_offer_a_nonexistent_upgrade(self):
        _seed_ladder()
        school = _school('Maxed', 'maxed', module='ai_import_enterprise',
                         pages=1000, used=1000)
        allowed, message, _ = page_quota.check_page_budget(school, 1)
        self.assertFalse(allowed)
        self.assertIn('largest plan', message)

    def test_refusing_does_not_charge_anything(self):
        school = _school('Untouched', 'untouched', pages=600, used=600)
        page_quota.check_page_budget(school, 50)
        row = AIImportUsage.objects.get(school=school)
        self.assertEqual(row.pages_processed, 600)


class ConsumeAndRefundTests(TestCase):
    def test_consume_increments_the_current_period(self):
        school = _school('Charge', 'charge', pages=600, used=10)
        page_quota.consume_pages(school, 25)
        self.assertEqual(AIImportUsage.objects.get(school=school).pages_processed, 35)

    def test_consume_is_a_no_op_for_an_unmetered_school(self):
        school = _school('Free', 'free-school', module=None)
        page_quota.consume_pages(school, 25)
        self.assertFalse(AIImportUsage.objects.filter(
            school=school, pages_processed__gt=0).exists())

    def test_consume_is_a_no_op_for_a_superuser(self):
        school = _school('SuperCharge', 'super-charge', pages=600, used=10)
        page_quota.consume_pages(school, 25, unlimited=True)
        self.assertEqual(AIImportUsage.objects.get(school=school).pages_processed, 10)

    def test_refund_gives_pages_back(self):
        school = _school('Refund', 'refund', pages=600, used=100)
        page_quota.refund_pages(school, 40)
        self.assertEqual(AIImportUsage.objects.get(school=school).pages_processed, 60)

    def test_refund_floors_at_zero(self):
        school = _school('OverRefund', 'over-refund', pages=600, used=10)
        page_quota.refund_pages(school, 999)
        self.assertEqual(AIImportUsage.objects.get(school=school).pages_processed, 0)

    def test_charge_then_refund_is_a_round_trip(self):
        school = _school('RoundTrip', 'round-trip', pages=600, used=200)
        page_quota.consume_pages(school, 30)
        page_quota.refund_pages(school, 30)
        self.assertEqual(AIImportUsage.objects.get(school=school).pages_processed, 200)


class UploadPageCountTests(TestCase):
    def test_a_selection_charges_only_the_selected_pages(self):
        self.assertEqual(page_quota.upload_page_count([2, 3, 4], 10, None), 3)

    def test_no_selection_charges_the_whole_pdf(self):
        self.assertEqual(page_quota.upload_page_count(None, 10, None), 10)

    def test_an_unreadable_pdf_counts_as_one_page_rather_than_raising(self):
        # The quota is not the right place to reject a corrupt upload — the
        # extraction pipeline reports that properly. One page keeps an
        # exhausted school blocked without over-charging for work that fails.
        self.assertEqual(page_quota.upload_page_count(None, None, b'not a pdf'), 1)
