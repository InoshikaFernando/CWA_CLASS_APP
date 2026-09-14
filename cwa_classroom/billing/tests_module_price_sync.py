"""The frontend path to changing a module's price, and why it kept being wrong.

Three modules displayed $10 in production while Stripe billed $9, for months.
The super-admin has a price field and a "Sync to Stripe" button, which is the
only repricing path a human can reach without a shell — so it is the path that
has to be right.

It was wrong in three ways, each silent:

* Editing the price said "updated" and changed nothing about what any card was
  charged. A Stripe Price is immutable; the form only moves the number in the
  app.
* Sync created its product under a fixed id, ``module_<slug>``, which is not
  the id ``sync_stripe_prices`` gave the products actually in the account. The
  lookup missed and a SECOND product was created for the same module.
* That new product was stamped ``metadata.module``, while the sync command
  matches on ``metadata.module_slug`` — so products made here were invisible
  to it and fell back to a six-name keyword table.

And one that only appears after a successful reprice: two active prices on one
product both answer to the same module_slug, so the next sync can repoint the
module back to the amount it was just moved off.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from billing.models import ModuleProduct
from billing.stripe_service import sync_module_to_stripe


@override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_CURRENCY='usd')
class SyncModuleToStripeTest(TestCase):

    def setUp(self):
        self.product = ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('10.00'), stripe_price_id='price_old_900',
        )
        self.new_price = SimpleNamespace(id='price_new_1000')

    def test_it_reuses_the_product_the_module_already_lives_on(self):
        """A second product for one module leaves two "Teachers Attendance"
        entries in Stripe and a sync that cannot tell which is real."""
        with patch('stripe.Price.retrieve') as retrieve, \
             patch('stripe.Product.modify') as modify, \
             patch('stripe.Product.create') as create, \
             patch('stripe.Price.create', return_value=self.new_price) as price_create, \
             patch('stripe.Price.modify'):
            retrieve.return_value = SimpleNamespace(
                id='price_old_900', product='prod_real', unit_amount=900)
            modify.return_value = SimpleNamespace(id='prod_real')

            sync_module_to_stripe(self.product)

        create.assert_not_called()
        self.assertEqual(price_create.call_args.kwargs['product'], 'prod_real')

    def test_a_module_with_no_price_yet_gets_a_product(self):
        ModuleProduct.objects.filter(pk=self.product.pk).update(stripe_price_id='')
        self.product.refresh_from_db()

        with patch('stripe.Product.retrieve',
                   side_effect=stripe.error.InvalidRequestError('no such product', None)), \
             patch('stripe.Product.create',
                   return_value=SimpleNamespace(id='module_teachers_attendance')) as create, \
             patch('stripe.Price.create', return_value=self.new_price):
            sync_module_to_stripe(self.product)

        self.assertEqual(
            create.call_args.kwargs['metadata']['module_slug'],
            'teachers_attendance',
        )

    def test_a_created_product_is_findable_by_the_sync_command(self):
        """metadata.module is not the key sync_stripe_prices reads. A product
        stamped only with that is invisible to it."""
        ModuleProduct.objects.filter(pk=self.product.pk).update(stripe_price_id='')
        self.product.refresh_from_db()

        with patch('stripe.Product.retrieve',
                   side_effect=stripe.error.InvalidRequestError('nope', None)), \
             patch('stripe.Product.create',
                   return_value=SimpleNamespace(id='module_teachers_attendance')) as create, \
             patch('stripe.Price.create', return_value=self.new_price):
            sync_module_to_stripe(self.product)

        self.assertIn('module_slug', create.call_args.kwargs['metadata'])

    def test_the_superseded_price_is_archived(self):
        """Both prices share a product and so share a module_slug. Leaving the
        old one active lets the next sync choose it and undo the reprice."""
        with patch('stripe.Price.retrieve') as retrieve, \
             patch('stripe.Product.modify', return_value=SimpleNamespace(id='prod_real')), \
             patch('stripe.Price.create', return_value=self.new_price), \
             patch('stripe.Price.modify') as price_modify:
            retrieve.return_value = SimpleNamespace(
                id='price_old_900', product='prod_real', unit_amount=900)

            sync_module_to_stripe(self.product)

        price_modify.assert_called_once_with('price_old_900', active=False)

    def test_the_row_is_repointed(self):
        with patch('stripe.Price.retrieve') as retrieve, \
             patch('stripe.Product.modify', return_value=SimpleNamespace(id='prod_real')), \
             patch('stripe.Price.create', return_value=self.new_price), \
             patch('stripe.Price.modify'):
            retrieve.return_value = SimpleNamespace(
                id='price_old_900', product='prod_real', unit_amount=900)

            sync_module_to_stripe(self.product)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stripe_price_id, 'price_new_1000')

    def test_a_failed_archive_does_not_lose_the_reprice(self):
        """Archiving is hygiene. Raising here would leave the new price created
        in Stripe and the row still on the old one."""
        with patch('stripe.Price.retrieve') as retrieve, \
             patch('stripe.Product.modify', return_value=SimpleNamespace(id='prod_real')), \
             patch('stripe.Price.create', return_value=self.new_price), \
             patch('stripe.Price.modify',
                   side_effect=stripe.error.APIConnectionError('down')):
            retrieve.return_value = SimpleNamespace(
                id='price_old_900', product='prod_real', unit_amount=900)

            sync_module_to_stripe(self.product)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stripe_price_id, 'price_new_1000')


class ModuleProductEditWarningTest(TestCase):
    """Editing the price must say what it did NOT do."""

    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            username='root', email='root@test.com', password='x')
        self.client.login(username='root', password='x')
        self.product = ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('9.00'), stripe_price_id='price_old_900',
        )

    def _post(self, price):
        return self.client.post(
            reverse('billing_admin_module_edit', args=[self.product.pk]),
            {'name': 'Teachers Attendance', 'price': price}, follow=True,
        )

    def test_changing_the_price_warns_that_stripe_still_charges_the_old_one(self):
        resp = self._post('10.00')
        text = ' '.join(str(m) for m in resp.context['messages'])
        self.assertIn('Stripe still charges the old amount', text)
        self.assertIn('Sync to Stripe', text)

    def test_the_price_is_still_saved(self):
        """Warn, don't refuse — the admin is where a price is decided."""
        self._post('10.00')
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('10.00'))

    def test_editing_only_the_name_does_not_warn(self):
        resp = self.client.post(
            reverse('billing_admin_module_edit', args=[self.product.pk]),
            {'name': 'Teacher Attendance', 'price': '9.00'}, follow=True,
        )
        text = ' '.join(str(m) for m in resp.context['messages'])
        self.assertNotIn('Stripe still charges', text)

    def test_a_module_with_no_stripe_price_does_not_warn(self):
        """Nothing is being charged yet, so nothing is out of step."""
        ModuleProduct.objects.filter(pk=self.product.pk).update(stripe_price_id='')
        resp = self._post('10.00')
        text = ' '.join(str(m) for m in resp.context['messages'])
        self.assertNotIn('Stripe still charges', text)
