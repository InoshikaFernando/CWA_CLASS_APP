"""Pull real vendor charges into Expense rows from billing APIs.

Runs the auto-sync pullers so the income-vs-expense dashboard reflects actual
charges without manual updates:

  * AI usage (Anthropic) — always runs; sums the internal taskqueue.AIUsageLog
    ledger (PDF scan + marking + worksheets). No key required.
  * DigitalOcean — runs only when settings.DIGITALOCEAN_API_TOKEN is set;
    pulls the real monthly invoices (any addon included) and supersedes the
    recurring DO estimate for those months.
  * GitHub — uses the GitHub credentials already configured for the AI-usage
    dashboard (overridable with GITHUB_BILLING_TOKEN / GITHUB_BILLING_ACCOUNT);
    reads the enhanced billing usage report and books the net charge per month
    (Actions minutes, Packages, LFS, Copilot — whatever is on the bill). A
    month inside the free allowance nets zero and is recorded as such.
  * Billed AI spend (Anthropic + OpenAI) — runs only for a vendor whose admin
    key is set (ANTHROPIC_ADMIN_API_KEY / OPENAI_ADMIN_API_KEY); reads what the
    vendor actually billed from its own cost API and supersedes that month's
    token estimate. A vendor with no key is reported as skipped, and its months
    keep the estimate — never a silent $0.

Each puller is idempotent and best-effort (a vendor outage logs a warning and
skips, never aborts the others). Intended to run monthly via cron alongside
materialize_recurring_expenses.

    python manage.py sync_vendor_charges
"""
from django.core.management.base import BaseCommand

from billing.reporting import (
    sync_ai_usage_expenses, sync_ai_vendor_expenses, sync_digitalocean_expenses,
    sync_github_expenses,
)


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

        gh = sync_github_expenses()
        if gh:
            self.stdout.write(f'GitHub billing months synced: {gh}')
        else:
            self.stdout.write(
                'GitHub: skipped (no billing token/account resolved from '
                'AI_DASHBOARD_GITHUB_TOKEN + AI_DASHBOARD_GITHUB_REPO or the '
                'GITHUB_BILLING_* overrides, or every month was refused — see '
                'the log for GitHub\'s reason)')

        # Runs last: it replaces the token estimate synced above with what the
        # vendor billed, for every month it can cover.
        billed = sync_ai_vendor_expenses()
        self.stdout.write(f'Billed AI rows synced: {billed["written"]}')
        for provider, reason in billed['skipped']:
            self.stdout.write(self.style.WARNING(
                f'  {provider}: no billed figure ({reason}) — that month keeps '
                f'the token estimate'))

        self.stdout.write(self.style.SUCCESS('Vendor charge sync complete.'))
