"""Turn ``question_automation`` into three tiers and price them.

Migration 0051 seeded a single ``question_automation`` product at the $10
placeholder every newly-catalogued module got. That slug is gone as of 0054:
the module is now tiered on how many schedules run at once, because that —
not the student roll — is what the weekly build and its downstream homework
notifications scale with.

Values are a frozen copy of ``billing/catalogue.py``; migrations must not
import live app code, which will keep changing underneath them.

The untiered row is only removed when nothing in Stripe points at it. This
branch has never shipped, so on every real environment that row will have been
created moments earlier by 0051 with a blank ``stripe_price_id`` and will go
cleanly. If somebody has already run ``sync_stripe_prices`` against it, the
row stays and is merely deactivated — deleting it would orphan a live Stripe
price, and silently dropping a product somebody could be billed for is worse
than leaving an inert row behind for an operator to look at.
"""

from django.db import migrations

RETIRED = 'question_automation'

TIERS = [
    {'module': 'question_automation_starter',
     'name': 'Question Automation - Starter',
     'price': 10.00, 'schedules_limit': 15},
    {'module': 'question_automation_professional',
     'name': 'Question Automation - Professional',
     'price': 25.00, 'schedules_limit': 75},
    {'module': 'question_automation_unlimited',
     'name': 'Question Automation - Unlimited',
     'price': 60.00, 'schedules_limit': None},
]


def seed(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleSubscription = apps.get_model('billing', 'ModuleSubscription')

    for tier in TIERS:
        ModuleProduct.objects.get_or_create(
            module=tier['module'],
            defaults={
                'name': tier['name'],
                'price': tier['price'],
                'schedules_limit': tier['schedules_limit'],
                'is_active': True,
            },
        )

    # Any school that somehow holds the retired slug is moved to Starter rather
    # than losing the module. Its limit is the smallest, but a school that was
    # granted the untiered version was never promised more, and a silent
    # downgrade beats a silent removal: the module keeps working and the
    # allowance is visible in Billing.
    ModuleSubscription.objects.filter(module=RETIRED).update(
        module='question_automation_starter',
    )

    unsynced = ModuleProduct.objects.filter(module=RETIRED, stripe_price_id='')
    if unsynced.exists():
        unsynced.delete()
    else:
        ModuleProduct.objects.filter(module=RETIRED).update(is_active=False)


def reverse_seed(apps, schema_editor):
    """Restore the single product and fold every tier back onto it."""
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleSubscription = apps.get_model('billing', 'ModuleSubscription')

    ModuleProduct.objects.get_or_create(
        module=RETIRED,
        defaults={'name': 'Question Automation', 'price': 10.00,
                  'is_active': True},
    )
    ModuleProduct.objects.filter(module=RETIRED).update(is_active=True)

    # Subscriptions first: unique_together is (school_subscription, module), so
    # a school holding two tiers would collide on the way back. Keep the
    # strongest, drop the rest, then rename what is left.
    for strongest in ('question_automation_unlimited',
                      'question_automation_professional',
                      'question_automation_starter'):
        for row in ModuleSubscription.objects.filter(module=strongest):
            already = ModuleSubscription.objects.filter(
                school_subscription_id=row.school_subscription_id,
                module=RETIRED,
            ).exists()
            if already:
                row.delete()
            else:
                row.module = RETIRED
                row.save(update_fields=['module'])

    ModuleProduct.objects.filter(
        module__in=[t['module'] for t in TIERS], stripe_price_id='',
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0054_question_automation_tiers'),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
