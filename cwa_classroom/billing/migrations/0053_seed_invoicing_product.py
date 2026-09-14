"""Give ``invoicing`` a product row so it can actually be bought.

Same shape and the same reason as 0051: a slug can reach ``MODULE_CHOICES``
and the registry — enforceable, audited, shown in the admin — and still have
no ``ModuleProduct``, which means no price and no ``stripe_price_id``. That
gap is invisible from the sync command, because ``sync_stripe_prices``
iterates ``ModuleProduct.objects.filter(is_active=True)``: a module with no
row is not reported missing, it simply is not iterated.

The values are a frozen copy of ``billing/catalogue.py``. Migrations must not
import live app code — the catalogue will change and this migration must keep
meaning what it meant when it ran.

$10.00 is a seed default, not a pricing decision. Invoicing is the largest
feature in the catalogue (fee schedules, invoice numbering, line items,
part-payments and reversals, parent card checkout) and it is the one most
likely to be repriced before it is ever charged for. Set the real number in
the admin before running ``sync_stripe_prices --create-missing``: a Stripe
Price is immutable, so a wrong amount means an orphaned price and a re-point,
not an edit.
"""

from django.db import migrations

INVOICING = {
    'module': 'invoicing',
    'name': 'Student Invoicing',
    'price': 10.00,
}


def seed(apps, schema_editor):
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleProduct.objects.get_or_create(
        module=INVOICING['module'],
        defaults={
            'name': INVOICING['name'],
            'price': INVOICING['price'],
            'is_active': True,
        },
    )


def reverse_seed(apps, schema_editor):
    """Only remove a row nothing in Stripe points at.

    A row that has been synced carries a ``stripe_price_id``, and deleting it
    would orphan a live Stripe price while leaving any school subscribed to it
    pointing at nothing.
    """
    ModuleProduct = apps.get_model('billing', 'ModuleProduct')
    ModuleProduct.objects.filter(
        module=INVOICING['module'], stripe_price_id='',
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0052_invoicing_module'),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
