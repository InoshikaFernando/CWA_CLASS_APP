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

from django.apps import apps as global_apps
from django.contrib import admin
from django.test import TestCase

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
