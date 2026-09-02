"""
At most one Package carries ``is_default``.

``CompleteProfileView._get_student_package()`` resolves the default with
``filter(is_default=True).first()`` under ``ordering = ['order', 'price']``.
Two defaults therefore never raised — they quietly put every new school student
on whichever package sorted first, which is exactly the kind of invisible pick
that put a student on the wrong price to begin with.
"""
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.apps import apps as global_apps
from django.contrib import admin
from django.test import TestCase, override_settings

from billing.models import Package


def _package(name, price='19.00', order=1, is_default=False, **kw):
    return Package.objects.create(
        name=name, price=Decimal(price), order=order, is_default=is_default,
        class_limit=0, trial_days=14, is_active=True,
        stripe_price_id=kw.pop('stripe_price_id', 'price_x'), **kw,
    )


class SingleDefaultPackageTests(TestCase):

    def test_marking_a_package_default_demotes_the_previous_one(self):
        old = _package('Student Plan', order=1, is_default=True)
        new = _package('Wizards', order=2)

        new.is_default = True
        new.save()

        old.refresh_from_db()
        new.refresh_from_db()
        self.assertFalse(old.is_default)
        self.assertTrue(new.is_default)
        self.assertEqual(Package.objects.filter(is_default=True).count(), 1)

    def test_saving_a_non_default_package_leaves_the_default_alone(self):
        default = _package('Wizards', order=1, is_default=True)
        other = _package('Student Plan', order=2)

        other.price = Decimal('29.00')
        other.save()

        default.refresh_from_db()
        self.assertTrue(default.is_default)

    def test_re_saving_the_default_keeps_it_default(self):
        default = _package('Wizards', is_default=True)

        default.trial_days = 30
        default.save()

        default.refresh_from_db()
        self.assertTrue(default.is_default)

    def test_student_package_lookup_follows_the_new_default(self):
        from accounts.views import CompleteProfileView

        _package('Student Plan', price='19.00', order=1, is_default=True)
        wizards = _package('Wizards', price='29.00', order=2)

        wizards.is_default = True
        wizards.save()

        # Cheaper and earlier in `ordering`, so a stale second default would win.
        self.assertEqual(CompleteProfileView()._get_student_package(), wizards)

    def test_lookup_falls_back_to_cheapest_paid_when_nothing_is_default(self):
        from accounts.views import CompleteProfileView

        cheap = _package('Cheap', price='9.00', order=2)
        _package('Dear', price='39.00', order=1)

        self.assertEqual(CompleteProfileView()._get_student_package(), cheap)


class KeepOneDefaultMigrationTests(TestCase):
    """The invariant has to hold for rows that predate it, too."""

    def test_existing_duplicate_defaults_are_reduced_to_the_resolved_one(self):
        migration = import_module('billing.migrations.0046_single_default_package')

        keeper = _package('Student Plan', price='19.00', order=1)
        loser = _package('Wizards', price='29.00', order=2)
        # Bypass save() to build the pre-migration state.
        Package.objects.filter(pk__in=[keeper.pk, loser.pk]).update(is_default=True)

        migration.keep_one_default(global_apps, None)

        keeper.refresh_from_db()
        loser.refresh_from_db()
        # `ordering = ['order', 'price']` already resolved to this one, so the
        # migration must not move anybody to a different package.
        self.assertTrue(keeper.is_default)
        self.assertFalse(loser.is_default)

    def test_no_defaults_at_all_is_left_alone(self):
        migration = import_module('billing.migrations.0046_single_default_package')
        pkg = _package('Wizards')

        migration.keep_one_default(global_apps, None)

        pkg.refresh_from_db()
        self.assertFalse(pkg.is_default)


class PackageAdminTests(TestCase):
    """The two fields that decide who pays what are settable from the admin
    list, not buried on the change form."""

    def test_default_and_price_id_are_visible_and_editable(self):
        options = admin.site._registry[Package]
        self.assertIn('is_default', options.list_display)
        self.assertIn('stripe_price_id', options.list_display)
        self.assertIn('is_default', options.list_editable)


class MakeSoleStudentPackageActionTests(TestCase):
    """The admin action does the sync, the default flag and the retirement of
    the other packages together — or does nothing at all."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        cls.staff = CustomUser.objects.create_user(
            username='pkg_admin', email='pkg_admin@test.com',
            password='testpass123', is_staff=True, is_superuser=True,
        )

    def setUp(self):
        self.wizards = _package('Wizards', price='19.00', order=2, stripe_price_id='')
        self.old = _package('Student Plan', price='19.00', order=1,
                            is_default=True, stripe_price_id='price_nzd_19')
        self.options = admin.site._registry[Package]

    # -- helpers -------------------------------------------------------
    def _request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        request = RequestFactory().post('/admin/billing/package/')
        request.user = self.staff
        request.session = 'session'
        request._messages = FallbackStorage(request)
        return request

    def _run(self, queryset, request=None):
        from billing.admin import make_sole_student_package
        request = request or self._request()
        make_sole_student_package(self.options, request, queryset)
        return [str(m) for m in request._messages]

    def _sync_writes(self, price_id='price_usd_19'):
        """Stand in for sync_stripe_prices: it writes price IDs to the DB."""
        def _fake(*args, **kwargs):
            Package.objects.filter(pk=self.wizards.pk).update(stripe_price_id=price_id)
        return _fake

    # -- tests ---------------------------------------------------------
    @patch('billing.stripe_service.stripe.Price.retrieve',
           return_value=SimpleNamespace(id='price_usd_19', currency='usd'))
    def test_syncs_sets_default_and_retires_the_others(self, _retrieve):
        with patch('billing.admin.call_command', side_effect=self._sync_writes()):
            messages_out = self._run(Package.objects.filter(pk=self.wizards.pk))

        self.wizards.refresh_from_db()
        self.old.refresh_from_db()

        self.assertEqual(self.wizards.stripe_price_id, 'price_usd_19')
        self.assertTrue(self.wizards.is_default)
        self.assertTrue(self.wizards.is_active)
        self.assertFalse(self.old.is_default)
        self.assertFalse(self.old.is_active)
        self.assertIn('only student package', ' '.join(messages_out))

    @patch('billing.stripe_service.stripe.Price.retrieve',
           return_value=SimpleNamespace(id='price_usd_19', currency='usd'))
    def test_new_default_is_what_a_school_student_gets(self, _retrieve):
        from accounts.views import CompleteProfileView

        with patch('billing.admin.call_command', side_effect=self._sync_writes()):
            self._run(Package.objects.filter(pk=self.wizards.pk))

        self.assertEqual(CompleteProfileView()._get_student_package(), self.wizards)

    @patch('billing.stripe_service.stripe.Price.retrieve',
           return_value=SimpleNamespace(id='price_nzd_19', currency='nzd'))
    def test_a_non_usd_price_rolls_the_whole_action_back(self, _retrieve):
        with patch('billing.admin.call_command',
                   side_effect=self._sync_writes('price_nzd_19')):
            messages_out = self._run(Package.objects.filter(pk=self.wizards.pk))

        self.wizards.refresh_from_db()
        self.old.refresh_from_db()

        # Including the price ID the sync had already written.
        self.assertEqual(self.wizards.stripe_price_id, '')
        self.assertFalse(self.wizards.is_default)
        self.assertTrue(self.old.is_active, 'the other package must stay sellable')
        self.assertTrue(self.old.is_default)
        joined = ' '.join(messages_out)
        self.assertIn('Nothing was changed', joined)
        self.assertIn('NZD', joined)

    def test_refuses_more_than_one_selected_package(self):
        messages_out = self._run(Package.objects.all())

        self.wizards.refresh_from_db()
        self.assertFalse(self.wizards.is_default)
        self.assertIn('exactly one package', ' '.join(messages_out))

    def test_refuses_a_free_package(self):
        free = _package('Free', price='0.00', order=3, stripe_price_id='')

        messages_out = self._run(Package.objects.filter(pk=free.pk))

        free.refresh_from_db()
        self.assertFalse(free.is_default)
        self.assertTrue(self.old.is_active)
        self.assertIn('is free', ' '.join(messages_out))

    @patch('billing.stripe_service.stripe.Price.retrieve',
           return_value=SimpleNamespace(id='price_usd_19', currency='usd'))
    def test_writes_an_audit_entry(self, _retrieve):
        from audit.models import AuditLog

        with patch('billing.admin.call_command', side_effect=self._sync_writes()):
            self._run(Package.objects.filter(pk=self.wizards.pk))

        entry = AuditLog.objects.filter(
            action='billing_sole_student_package_set',
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.detail['package_name'], 'Wizards')
        self.assertEqual(entry.detail['retired_packages'], ['Student Plan'])

    def test_the_action_is_registered_on_the_package_admin(self):
        self.assertIn(
            'make_sole_student_package',
            self.options.get_actions(self._request()),
        )

    @patch('billing.stripe_service.stripe.Price.retrieve',
           return_value=SimpleNamespace(id='price_usd_19', currency='usd'))
    @patch('billing.management.commands.sync_stripe_prices.stripe')
    def test_end_to_end_through_the_real_sync_command(self, mock_stripe, _retrieve):
        """No stand-in: the action really runs sync_stripe_prices, which really
        picks the USD price over the NZD one at the same amount."""
        def _price(price_id, currency, name):
            return SimpleNamespace(
                id=price_id, unit_amount=1900, currency=currency,
                product=SimpleNamespace(id=f'prod_{price_id}', name=name, metadata={}),
                recurring=SimpleNamespace(interval='month'),
            )

        listing = MagicMock()
        listing.data = [
            _price('price_usd_19', 'usd', 'Wizards Student'),
            _price('price_nzd_19', 'nzd', 'Student Plan'),
        ]
        listing.has_more = False
        empty = MagicMock()
        empty.data = []
        empty.has_more = False
        mock_stripe.Price.list.return_value = listing
        mock_stripe.Product.list.return_value = empty

        with override_settings(STRIPE_SECRET_KEY='sk_test_fake'):
            messages_out = self._run(Package.objects.filter(pk=self.wizards.pk))

        self.wizards.refresh_from_db()
        self.old.refresh_from_db()

        self.assertEqual(self.wizards.stripe_price_id, 'price_usd_19')
        self.assertTrue(self.wizards.is_default)
        self.assertFalse(self.old.is_active)
        self.assertIn('only student package', ' '.join(messages_out))
