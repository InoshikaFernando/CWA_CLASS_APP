"""Test helpers for the AI page allowance.

Not a test module — named so pytest's ``python_files`` does not collect it.

Spending AI pages needs an AI module. That is now true wherever the upload
starts (homework, worksheet or AI import), so any test that drives a real PDF
upload has to say which kind of school it is testing: one that can afford AI, or
one that cannot. Both are worth testing; neither should be implied by silence.

    from billing.testing import grant_ai_pages

    def setUp(self):
        grant_ai_pages(self.school)        # this school can spend AI pages

A test that wants the refusal simply leaves the school without a module, which
is the default state of every fixture school.
"""
from decimal import Decimal

from django.utils import timezone


DEFAULT_MODULE = 'ai_import_professional'
DEFAULT_PAGES = 600


def grant_ai_pages(school, *, pages=DEFAULT_PAGES, module=DEFAULT_MODULE):
    """Give ``school`` an active AI module worth ``pages`` a month.

    Creates whatever the school is missing — an institute plan, a subscription,
    the catalogue row — so a test can call it on a bare ``School`` without
    knowing how billing is wired. Returns the ``ModuleSubscription``.
    """
    from billing.models import (
        InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
    )

    subscription = SchoolSubscription.objects.filter(school=school).first()
    if subscription is None:
        plan, _ = InstitutePlan.objects.get_or_create(
            slug=f'{school.slug}-test-plan',
            defaults={
                'name': f'{school.name} Test Plan',
                'price': Decimal('89.00'),
                'class_limit': 50,
                'student_limit': 1000,
                'invoice_limit_yearly': 500,
                'extra_invoice_rate': Decimal('0.30'),
            },
        )
        subscription = SchoolSubscription.objects.create(
            school=school, plan=plan, status='active',
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )

    ModuleProduct.objects.update_or_create(
        module=module,
        defaults={
            'name': f'AI Import — {module.rsplit("_", 1)[-1].title()}',
            'price': Decimal('30.00'),
            'pages_per_month': pages,
            'is_active': True,
        },
    )
    module_subscription, _ = ModuleSubscription.objects.get_or_create(
        school_subscription=subscription, module=module,
        defaults={'is_active': True},
    )
    if not module_subscription.is_active:
        module_subscription.is_active = True
        module_subscription.save(update_fields=['is_active'])
    return module_subscription
