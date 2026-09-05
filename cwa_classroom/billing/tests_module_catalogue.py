"""A module you can enforce but nobody can buy.

The registry guard already holds ``registry.REGISTRY`` and
``ModuleSubscription.MODULE_CHOICES`` to the same set, so a module cannot be
enforceable-but-unsellable *in the enum*. That was not enough. Selling needs a
third thing — a ``ModuleProduct`` row carrying the price and the Stripe price
id — and nothing checked it, so five modules shipped that could be subscribed
to and gated but had no price anywhere.

The failure was completely silent. ``sync_stripe_prices`` iterates
``ModuleProduct.objects.filter(is_active=True)``, so a module with no row is
not reported missing; it simply is not iterated, and the summary line still
reads "Module Products: updated 0, skipped 0".

These tests close the loop: enum → catalogue → database row.
"""

import pytest

from billing import catalogue, registry
from billing.models import ModuleProduct, ModuleSubscription


def test_every_sellable_module_has_a_price_in_the_catalogue():
    """A slug you can subscribe to but cannot price is a slug you cannot sell."""
    sellable = {slug for slug, _label in ModuleSubscription.MODULE_CHOICES}
    priced = catalogue.slugs()

    assert sellable - priced == set(), (
        'Sellable but absent from billing/catalogue.py, so no price exists and '
        f'sync_stripe_prices will skip them silently: {sorted(sellable - priced)}')
    assert priced - sellable == set(), (
        'Priced in billing/catalogue.py but not sellable — either the slug is '
        f'stale or it was dropped from MODULE_CHOICES: {sorted(priced - sellable)}')


def test_the_catalogue_and_the_registry_describe_the_same_product():
    """Three files, one product. Any pair disagreeing is a bug somebody ships."""
    assert catalogue.slugs() == registry.slugs(), (
        'billing/catalogue.py and billing/registry.py disagree about which '
        'modules exist: '
        f'only in catalogue {sorted(catalogue.slugs() - registry.slugs())}, '
        f'only in registry {sorted(registry.slugs() - catalogue.slugs())}')


def test_the_leaderboard_is_in_neither():
    """Points and the leaderboard are free, so they must not be priced.

    Pinned here as well as in tests_module_registry because the two failures
    are different: the registry one would gate the board, this one would put a
    price on a thing that is meant to drive engagement.
    """
    assert 'rewards' not in catalogue.slugs()
    assert 'rewards' not in {s for s, _ in ModuleSubscription.MODULE_CHOICES}


@pytest.mark.django_db
def test_the_seed_command_covers_every_sellable_module():
    """Running the command must leave no sellable module without a price.

    This tests the command rather than the migration on purpose. ``conftest``
    skips migrations on SQLite (tables are built from models), and CI runs
    SQLite — so the seed *migration* never executes in this suite and a test
    asserting rows-after-migrate would fail everywhere except production.
    The command is the mechanism both paths share, so proving it covers the
    full slug list is the assertion that actually means something here.
    """
    from io import StringIO
    from django.core.management import call_command

    err = StringIO()
    call_command('seed_module_products', stdout=StringIO(), stderr=err)

    sellable = {slug for slug, _label in ModuleSubscription.MODULE_CHOICES}
    rows = set(ModuleProduct.objects.values_list('module', flat=True))

    assert sellable - rows == set(), (
        'Sellable modules still without a ModuleProduct row after seeding — '
        'they cannot be priced, shown at checkout, or synced to Stripe: '
        f'{sorted(sellable - rows)}')
    assert err.getvalue() == '', (
        f'seed_module_products reported a problem: {err.getvalue()}')


@pytest.mark.django_db
def test_seed_command_is_idempotent_and_never_edits_a_price():
    """Prices are set by people in the admin; a deploy must not revert them."""
    from io import StringIO
    from decimal import Decimal
    from django.core.management import call_command

    call_command('seed_module_products', stdout=StringIO(), stderr=StringIO())

    mp = ModuleProduct.objects.get(module='brainbuzz')
    mp.price = Decimal('42.00')
    mp.save(update_fields=['price'])

    before = ModuleProduct.objects.count()
    call_command('seed_module_products', stdout=StringIO(), stderr=StringIO())

    assert ModuleProduct.objects.count() == before, 'seeding created a duplicate'
    mp.refresh_from_db()
    assert mp.price == Decimal('42.00'), (
        'seed_module_products overwrote a price set by hand')


@pytest.mark.django_db
def test_a_sellable_module_with_no_catalogue_entry_is_reported_not_skipped():
    """The gap this whole file exists to close must not reappear inside it.

    If a slug is sellable but uncatalogued, the command creates nothing for it.
    Doing that quietly would reproduce the original failure one layer up, so it
    must be written to stderr.
    """
    from io import StringIO
    from unittest.mock import patch
    from django.core.management import call_command

    choices = list(ModuleSubscription.MODULE_CHOICES) + [('ghost_module', 'Ghost')]
    err = StringIO()
    with patch.object(ModuleSubscription, 'MODULE_CHOICES', choices):
        call_command('seed_module_products', stdout=StringIO(), stderr=err)

    assert 'ghost_module' in err.getvalue(), (
        'a sellable module with no price was skipped silently')
