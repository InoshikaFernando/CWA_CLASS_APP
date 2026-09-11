"""Seed ModuleProduct rows for the modules that had none.

Five modules reached MODULE_CHOICES without a product row: report_automation
and question_automation (new here), and brainbuzz, worksheets and
whatsapp_notifications (features that already existed and were free). A module
with no ModuleProduct has no price and no stripe_price_id, so it can be gated
and audited but never bought — and ``sync_stripe_prices`` skips it silently,
because that command only walks ``ModuleProduct.objects.filter(is_active=True)``.

Values come from ``billing.catalogue``, the same source the
``seed_module_products`` command reads, so a deploy and a manual run cannot
disagree. get_or_create, so an existing price is never overwritten.
"""

from django.db import migrations

# Frozen copy of the catalogue at the time of this migration. Migrations must
# not import live application code: this file has to keep replaying identically
# years from now, whatever billing/catalogue.py has since become.
NEW_MODULES = [
    {'module': 'report_automation',
     'name': 'Student Report Automation', 'price': 10.00},
    {'module': 'question_automation',
     'name': 'Question Automation', 'price': 10.00},
    {'module': 'brainbuzz',
     'name': 'BrainBuzz Live Quiz', 'price': 10.00},
    {'module': 'worksheets',
     'name': 'Worksheets', 'price': 10.00},
    {'module': 'whatsapp_notifications',
     'name': 'WhatsApp Parent Notifications', 'price': 10.00},
]


def seed(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    for m in NEW_MODULES:
        ModuleProduct.objects.get_or_create(
            module=m['module'],
            defaults={'name': m['name'], 'price': m['price'], 'is_active': True},
        )


def reverse_seed(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleProduct.objects.filter(
        module__in=[m['module'] for m in NEW_MODULES],
        # Only remove rows this migration could have created. A row that has
        # been wired to Stripe is somebody's live product; unapplying a
        # migration must not delete it.
        stripe_price_id='',
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0050_drop_rewards_module_choice'),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
