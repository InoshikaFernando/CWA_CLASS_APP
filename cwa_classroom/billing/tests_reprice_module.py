"""Repricing a module, given that a Stripe Price cannot be edited.

Changing ``ModuleProduct.price`` in the admin moves the number on every page
and nothing else: the Stripe Price is immutable, and ``sync_stripe_prices``
skips the row because it already has a price id. So until this command there
was no supported way to change what a module charges — which is how production
displayed $10 for three modules Stripe billed at $9, for months, with no way to
correct it short of a shell session.

The distinction these tests exist to hold: repointing the product changes what
NEW subscribers pay, and moving an existing school is a price change for a
paying customer. Those must never be the same step.
"""
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import stripe
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import CustomUser
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from classroom.models import School


def _school_with_module(name, item_id='si_existing'):
    user = CustomUser.objects.create_user(
        username=f'{name}_admin', password='x', email=f'{name}@test.com')
    school = School.objects.create(name=name, slug=name.lower(), admin=user)
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{name}', price=Decimal('89.00'),
        stripe_price_id='price_plan', class_limit=5, student_limit=100,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status='active',
        stripe_subscription_id='sub_live',
    )
    ModuleSubscription.objects.create(
        school_subscription=sub, module='teachers_attendance',
        is_active=True, stripe_subscription_item_id=item_id,
    )
    return school


@override_settings(STRIPE_SECRET_KEY='sk_test_fake', STRIPE_CURRENCY='usd')
class RepriceModuleTest(TestCase):

    def setUp(self):
        self.product = ModuleProduct.objects.create(
            module='teachers_attendance', name='Teachers Attendance',
            price=Decimal('10.00'), stripe_price_id='price_old_900',
        )
        # What Stripe holds today: $9, the production case.
        self.old_price = SimpleNamespace(
            id='price_old_900', unit_amount=900, currency='usd',
            product='prod_ta',
        )

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command('reprice_module', *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    # -- selection -------------------------------------------------------

    def test_it_refuses_to_run_with_no_target(self):
        """A repricing command with no argument must not decide for itself
        which prices to change."""
        with self.assertRaises(CommandError):
            self._run()

    def test_an_unknown_slug_is_an_error_not_a_silent_no_op(self):
        with patch('stripe.Price.retrieve'):
            with self.assertRaises(CommandError):
                self._run('--module', 'not_a_module')

    # -- dry run ---------------------------------------------------------

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_dry_run_creates_nothing(self, mock_retrieve, mock_create):
        mock_retrieve.return_value = self.old_price
        out = self._run('--module', 'teachers_attendance')
        mock_create.assert_not_called()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stripe_price_id, 'price_old_900')
        self.assertIn('DRY RUN', out)

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_dry_run_names_both_amounts(self, mock_retrieve, _mock_create):
        mock_retrieve.return_value = self.old_price
        out = self._run('--module', 'teachers_attendance')
        self.assertIn('9', out)
        self.assertIn('10', out)

    # -- applying --------------------------------------------------------

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_apply_creates_the_new_price_on_the_same_product(self, mock_retrieve, mock_create):
        """A new Product would orphan the metadata sync_stripe_prices matches on
        and leave two products for one module."""
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        self._run('--module', 'teachers_attendance', '--apply')

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['product'], 'prod_ta')
        self.assertEqual(kwargs['unit_amount'], 1000)
        self.assertEqual(kwargs['currency'], 'usd')

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_apply_repoints_the_row(self, mock_retrieve, mock_create):
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        self._run('--module', 'teachers_attendance', '--apply')

        self.product.refresh_from_db()
        self.assertEqual(self.product.stripe_price_id, 'price_new_1000')

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_a_module_already_charging_the_right_amount_is_left_alone(
            self, mock_retrieve, mock_create):
        mock_retrieve.return_value = SimpleNamespace(
            id='price_old_900', unit_amount=1000, currency='usd', product='prod_ta')
        out = self._run('--module', 'teachers_attendance', '--apply')
        mock_create.assert_not_called()
        self.assertIn('nothing to do', out)

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_a_module_with_no_price_is_sent_to_the_other_command(
            self, mock_retrieve, mock_create):
        ModuleProduct.objects.filter(pk=self.product.pk).update(stripe_price_id='')
        out = self._run('--module', 'teachers_attendance')
        mock_retrieve.assert_not_called()
        mock_create.assert_not_called()
        self.assertIn('sync_stripe_prices --create-missing', out)

    @patch('stripe.Price.create', side_effect=stripe.error.APIConnectionError('down'))
    @patch('stripe.Price.retrieve')
    def test_a_failed_creation_leaves_the_row_pointing_at_the_working_price(
            self, mock_retrieve, _mock_create):
        """Half a repricing is worse than none: a row pointing at nothing
        cannot be charged at all."""
        mock_retrieve.return_value = self.old_price
        self._run('--module', 'teachers_attendance', '--apply')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stripe_price_id, 'price_old_900')

    # -- existing subscribers --------------------------------------------

    @patch('stripe.SubscriptionItem.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_existing_schools_are_not_moved_by_default(
            self, mock_retrieve, mock_create, mock_modify):
        """Repointing the product is a catalogue change. Moving a paying school
        is a price rise, and must never happen as a side effect of one."""
        _school_with_module('Shanthi')
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        out = self._run('--module', 'teachers_attendance', '--apply')

        mock_modify.assert_not_called()
        self.assertIn('Shanthi', out)
        self.assertIn('stays at', out)

    @patch('stripe.SubscriptionItem.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_migrate_existing_moves_them_to_the_new_price(
            self, mock_retrieve, mock_create, mock_modify):
        _school_with_module('Shanthi')
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        self._run('--module', 'teachers_attendance', '--apply', '--migrate-existing')

        args, kwargs = mock_modify.call_args
        self.assertEqual(args[0], 'si_existing')
        self.assertEqual(kwargs['price'], 'price_new_1000')

    @patch('stripe.SubscriptionItem.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_a_migrated_school_is_not_charged_mid_cycle(
            self, mock_retrieve, mock_create, mock_modify):
        """A rise they were told about should land on the date they expect a
        bill, not as a surprise proration today."""
        _school_with_module('Shanthi')
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        self._run('--module', 'teachers_attendance', '--apply', '--migrate-existing')

        self.assertEqual(mock_modify.call_args.kwargs['proration_behavior'], 'none')

    @patch('stripe.SubscriptionItem.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_migrate_existing_dry_run_moves_nobody(
            self, mock_retrieve, mock_create, mock_modify):
        _school_with_module('Shanthi')
        mock_retrieve.return_value = self.old_price

        out = self._run('--module', 'teachers_attendance', '--migrate-existing')

        mock_create.assert_not_called()
        mock_modify.assert_not_called()
        self.assertIn('Shanthi', out)

    @patch('stripe.SubscriptionItem.modify',
           side_effect=stripe.error.InvalidRequestError('no such item', None))
    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_one_school_failing_to_move_is_reported_and_does_not_stop_the_rest(
            self, mock_retrieve, mock_create, _mock_modify):
        _school_with_module('Shanthi')
        _school_with_module('MHM', item_id='si_other')
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        out = self._run('--module', 'teachers_attendance', '--apply', '--migrate-existing')

        self.assertIn('FAILED', out)
        self.assertIn('Shanthi', out)
        self.assertIn('MHM', out)

    @patch('stripe.SubscriptionItem.modify')
    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_a_school_that_was_never_billed_is_not_migrated(
            self, mock_retrieve, mock_create, mock_modify):
        """No subscription item means nothing to move — that school is the
        separate unbilled-module problem, not a repricing one."""
        _school_with_module('Code Wizards', item_id='')
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        self._run('--module', 'teachers_attendance', '--apply', '--migrate-existing')

        mock_modify.assert_not_called()

    # -- --drifted -------------------------------------------------------

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_drifted_finds_the_mismatch_without_being_told_the_slug(
            self, mock_retrieve, mock_create):
        mock_retrieve.return_value = self.old_price
        mock_create.return_value = SimpleNamespace(id='price_new_1000')

        self._run('--drifted', '--apply')

        self.product.refresh_from_db()
        self.assertEqual(self.product.stripe_price_id, 'price_new_1000')

    @patch('stripe.Price.create')
    @patch('stripe.Price.retrieve')
    def test_drifted_is_quiet_when_everything_agrees(self, mock_retrieve, mock_create):
        mock_retrieve.return_value = SimpleNamespace(
            id='price_old_900', unit_amount=1000, currency='usd', product='prod_ta')
        out = self._run('--drifted')
        mock_create.assert_not_called()
        self.assertIn('Nothing to reprice', out)
