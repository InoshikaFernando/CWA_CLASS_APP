"""Pull real vendor charges into Expense rows from billing APIs.

Runs the auto-sync pullers so the income-vs-expense dashboard reflects actual
charges without manual updates:

  * AI usage (Anthropic) — always runs; sums the internal taskqueue.AIUsageLog
    ledger (PDF scan + marking + worksheets). No key required.
  * DigitalOcean — runs only when settings.DIGITALOCEAN_API_TOKEN is set;
    pulls the real monthly invoices (any addon included) and supersedes the
    recurring DO estimate for those months.

Each puller is idempotent and best-effort (a vendor outage logs a warning and
skips, never aborts the others). Intended to run monthly via cron alongside
materialize_recurring_expenses.

    python manage.py sync_vendor_charges
"""
from django.core.management.base import BaseCommand

from billing.reporting import sync_ai_usage_expenses, sync_digitalocean_expenses


class Command(BaseCommand):
    help = 'Sync real vendor charges (AI usage ledger + DigitalOcean invoices).'

    def handle(self, *args, **options):
        ai = sync_ai_usage_expenses()
        self.stdout.write(f'AI usage rows synced: {ai}')

        do = sync_digitalocean_expenses()
        if do:
            self.stdout.write(f'DigitalOcean invoice rows synced: {do}')
        else:
            self.stdout.write(
                'DigitalOcean: skipped (DIGITALOCEAN_API_TOKEN not set or no invoices)')

        self.stdout.write(self.style.SUCCESS('Vendor charge sync complete.'))
