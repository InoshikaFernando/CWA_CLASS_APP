"""
Management command: check_stripe_prices

Verify every Stripe price the app would charge against still exists and is
active. An archived price is invisible until a student tries to pay, at which
point Stripe answers "The price specified is inactive" and the student is shown
a generic "contact support" — which is exactly how one archived price blocked
every school student's payment page for two weeks in September 2026.

Run from cron alongside the other daily health checks, e.g.:

    0 7 * * * /home/cwa/CWA_CLASS_APP/venv/bin/python \\
        /home/cwa/CWA_CLASS_APP/cwa_classroom/manage.py check_stripe_prices

Exits non-zero when a price is unusable, so cron mail (or a CI step) surfaces
it rather than a silent green run. The same data is on the ops dashboard.
"""
import sys

from django.core.management.base import BaseCommand

from billing.stripe_health import get_stripe_price_health


class Command(BaseCommand):
    help = 'Verify every configured Stripe price is present and active.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh', action='store_true',
            help='Bypass the cache and re-query Stripe.',
        )

    def handle(self, *args, **options):
        health = get_stripe_price_health(use_cache=not options['fresh'])

        if health['status'] == 'unknown':
            self.stdout.write(self.style.WARNING(health['skipped']))
            return

        if not health['broken']:
            self.stdout.write(self.style.SUCCESS(
                f'All {health["checked"]} configured Stripe price(s) are active.'
            ))
            return

        self.stderr.write(self.style.ERROR(
            f'{len(health["broken"])} Stripe price(s) cannot be charged against — '
            f'students on them cannot pay:'
        ))
        for b in health['broken']:
            price = b['price_id'] or '(none set)'
            self.stderr.write(self.style.ERROR(
                f'  {b["kind"]} "{b["label"]}" (id={b["id"]}) {price}: {b["problem"]}'
            ))
            # Each problem gets its own remedy. One shared footer told an admin
            # to re-activate a price that was already active, which is twenty
            # minutes in the Stripe dashboard looking for a fault that is not
            # there.
            if b.get('fix'):
                self.stderr.write(f'      → {b["fix"]}')
        sys.exit(1)
