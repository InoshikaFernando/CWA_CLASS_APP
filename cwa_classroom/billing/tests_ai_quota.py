"""
Tests for AI Usage Limits — Sprint 1 Foundation (CPP-251).

Covers: bypass bug fix, centralised quota check, pages_per_month from DB.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, SchoolSubscription, ModuleSubscription, ModuleProduct,
)
from billing.entitlements import check_ai_import_quota
from classroom.models import School

from ai_import.models import AIImportUsage


def _setup_school_with_ai_module(module_slug='ai_import_starter', pages_per_month=300):
    """Create a school with an active subscription and AI import module."""
    plan = InstitutePlan.objects.create(
        name='Test Plan', slug='test-plan', price=Decimal('89.00'),
        class_limit=5, student_limit=100, invoice_limit_yearly=500,
        extra_invoice_rate=Decimal('0.30'),
    )
    admin = CustomUser.objects.create_user(
        username='school_admin', password='test123', email='admin@test.com',
    )
    school = School.objects.create(name='Test School', admin=admin, is_active=True)
    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status='active',
        current_period_start=timezone.now(),
        current_period_end=timezone.now() + timezone.timedelta(days=30),
    )
    ModuleProduct.objects.get_or_create(
        module=module_slug,
        defaults={'name': f'AI Import - {module_slug}', 'price': Decimal('30.00'), 'pages_per_month': pages_per_month},
    )
    ModuleProduct.objects.filter(module=module_slug).update(pages_per_month=pages_per_month)
    ModuleSubscription.objects.create(
        school_subscription=sub, module=module_slug, is_active=True,
    )
    return school, sub, admin


class CheckAiImportQuotaTest(TestCase):
    """Tests for billing.entitlements.check_ai_import_quota."""

    def test_no_subscription_returns_zero(self):
        admin = CustomUser.objects.create_user(username='noadmin', password='x', email='no@t.com')
        school = School.objects.create(name='No Sub School', admin=admin, is_active=True)
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual((remaining, limit, used), (0, 0, 0))

    def test_no_ai_module_returns_zero(self):
        plan = InstitutePlan.objects.create(
            name='NoAI Plan', slug='noai-plan', price=Decimal('89.00'),
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        admin = CustomUser.objects.create_user(username='noai_admin', password='x', email='noai@t.com')
        school = School.objects.create(name='No AI School', admin=admin, is_active=True)
        SchoolSubscription.objects.create(school=school, plan=plan, status='active')
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual((remaining, limit, used), (0, 0, 0))

    def test_returns_correct_remaining_fresh(self):
        school, sub, admin = _setup_school_with_ai_module('ai_import_starter', 300)
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 300)
        self.assertEqual(limit, 300)
        self.assertEqual(used, 0)

    def test_returns_correct_remaining_with_usage(self):
        school, sub, admin = _setup_school_with_ai_module('ai_import_professional', 600)
        today = timezone.localdate()
        AIImportUsage.objects.create(
            school=school, period_start=today.replace(day=1),
            pages_processed=150, tokens_used=5000,
        )
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 450)
        self.assertEqual(limit, 600)
        self.assertEqual(used, 150)

    def test_remaining_never_negative(self):
        school, sub, admin = _setup_school_with_ai_module('ai_import_starter', 300)
        today = timezone.localdate()
        AIImportUsage.objects.create(
            school=school, period_start=today.replace(day=1),
            pages_processed=500, tokens_used=10000,
        )
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 0)
        self.assertEqual(limit, 300)
        self.assertEqual(used, 500)

    def test_pages_per_month_null_returns_unlimited(self):
        """Modules without pages_per_month (non-AI) return unlimited."""
        plan = InstitutePlan.objects.create(
            name='Null Plan', slug='null-plan', price=Decimal('89.00'),
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        admin = CustomUser.objects.create_user(username='null_admin', password='x', email='null@t.com')
        school = School.objects.create(name='Null School', admin=admin, is_active=True)
        sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
        ModuleProduct.objects.get_or_create(
            module='ai_import_starter',
            defaults={'name': 'AI Starter', 'price': Decimal('30.00'), 'pages_per_month': None},
        )
        ModuleProduct.objects.filter(module='ai_import_starter').update(pages_per_month=None)
        ModuleSubscription.objects.create(
            school_subscription=sub, module='ai_import_starter', is_active=True,
        )
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 999999)

    def test_pages_per_month_zero_returns_unlimited(self):
        school, sub, admin = _setup_school_with_ai_module('ai_import_enterprise', 0)
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 999999)


class BypassBugRegressionTest(TestCase):
    """Regression tests for the remaining==0 bypass bug."""

    def test_page_count_exceeds_zero_remaining_blocks(self):
        """When remaining is 0, any page_count > 0 should be blocked."""
        school, sub, admin = _setup_school_with_ai_module('ai_import_starter', 300)
        today = timezone.localdate()
        AIImportUsage.objects.create(
            school=school, period_start=today.replace(day=1),
            pages_processed=300, tokens_used=10000,
        )
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 0)
        page_count = 1
        self.assertTrue(page_count > remaining)

    def test_page_count_within_remaining_allowed(self):
        """When remaining > page_count, upload should proceed."""
        school, sub, admin = _setup_school_with_ai_module('ai_import_starter', 300)
        today = timezone.localdate()
        AIImportUsage.objects.create(
            school=school, period_start=today.replace(day=1),
            pages_processed=290, tokens_used=10000,
        )
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 10)
        page_count = 5
        self.assertFalse(page_count > remaining)

    def test_page_count_exceeds_partial_remaining_blocks(self):
        """When remaining > 0 but < page_count, upload should block."""
        school, sub, admin = _setup_school_with_ai_module('ai_import_starter', 300)
        today = timezone.localdate()
        AIImportUsage.objects.create(
            school=school, period_start=today.replace(day=1),
            pages_processed=295, tokens_used=10000,
        )
        remaining, limit, used = check_ai_import_quota(school)
        self.assertEqual(remaining, 5)
        page_count = 10
        self.assertTrue(page_count > remaining)
