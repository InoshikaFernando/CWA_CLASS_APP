"""Create the ``ModuleProduct`` row for any sellable module that lacks one.

A module needs two things to be sold: a slug in
``ModuleSubscription.MODULE_CHOICES`` (so it can be subscribed to and enforced)
and a ``ModuleProduct`` row (so it has a price and a Stripe price id). Nothing
held those together, and they drifted: five modules shipped enforceable and
audited but with no product row at all — priceable in theory, invisible at
checkout, and silently skipped by ``sync_stripe_prices``.

This command closes that gap from :mod:`billing.catalogue`, and
``tests_module_catalogue`` fails the build if a sellable module has no entry
there, so the drift cannot recur.

**It never edits an existing row.** Prices are changed in the admin by people,
not by deploys; ``get_or_create`` means a price someone set by hand survives
every run of this. Only genuinely absent rows are created.

Usage::

    python manage.py seed_module_products --dry-run   # show what is missing
    python manage.py seed_module_products             # create it
"""

from django.core.management.base import BaseCommand

from billing import catalogue
from billing.models import ModuleProduct, ModuleSubscription


class Command(BaseCommand):
    help = 'Create ModuleProduct rows for sellable modules that have none.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be created without writing anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        sellable = [slug for slug, _label in ModuleSubscription.MODULE_CHOICES]
        existing = set(ModuleProduct.objects.values_list('module', flat=True))

        created = 0
        skipped = 0
        uncatalogued = []

        self.stdout.write(self.style.MIGRATE_HEADING('=== Module Products ==='))

        for slug in sellable:
            if slug in existing:
                skipped += 1
                continue

            defaults = catalogue.defaults_for(slug)
            if defaults is None:
                # Sellable but with no price anywhere. Surfaced loudly rather
                # than skipped: this is exactly the silent gap the command
                # exists to close, so it must not become a silent gap itself.
                uncatalogued.append(slug)
                continue

            name = defaults.pop('name')
            price = defaults.pop('price')

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'  [DRY RUN] {slug} — would create "{name}" at ${price}/mo'
                ))
            else:
                ModuleProduct.objects.get_or_create(
                    module=slug,
                    defaults={'name': name, 'price': price,
                              'is_active': True, **defaults},
                )
                self.stdout.write(self.style.SUCCESS(
                    f'  [CREATED] {slug} — "{name}" at ${price}/mo'
                ))
            created += 1

        action = 'would create' if dry_run else 'created'
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Summary ==='))
        self.stdout.write(f'  {action} {created}, already present {skipped}')

        if uncatalogued:
            # Not an exception: the rows that could be made were made. But the
            # exit must be visible, because a module with no price is a module
            # nobody can buy.
            self.stderr.write(self.style.ERROR(
                '\n  Sellable but absent from billing/catalogue.py, so no price '
                'could be set:\n    ' + '\n    '.join(sorted(uncatalogued))
                + '\n  Add them to MODULE_CATALOGUE and re-run.'
            ))

        if not dry_run and created:
            self.stdout.write(
                '\n  Next: create the Stripe products and prices with\n'
                '    python manage.py sync_stripe_prices --create-missing --dry-run'
            )
