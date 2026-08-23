"""Summarise AI classification usage and cost.

Prints pages, tokens, estimated cost and derived $/page broken down by vendor
(Anthropic / OpenAI) and source (worksheet / ai_import / homework) over an
optional time window — so we can sanity-check real cost against what we charge,
and see which vendor a rising bill belongs to.

    python manage.py ai_usage_report --days 30
    python manage.py ai_usage_report --days 30 --format markdown   # for the dashboard issue
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from taskqueue.dashboard import aggregate_usage, build_usage_markdown
from taskqueue.models import AIUsageLog


class Command(BaseCommand):
    help = 'Summarise AI usage and estimated cost by source.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=None,
            help='Only include usage from the last N days (default: all time).',
        )
        parser.add_argument(
            '--format', choices=['table', 'markdown'], default='table',
            help='Output format: human table (default) or GitHub-flavoured markdown.',
        )

    def handle(self, *args, **options):
        days = options['days']

        if options['format'] == 'markdown':
            # Delegate to the shared builder so the CLI and the published
            # dashboard render identically (generation table + grading + total).
            self.stdout.write(build_usage_markdown(days=days))
            return

        qs = AIUsageLog.objects.all()
        if days:
            since = timezone.now() - timezone.timedelta(days=days)
            qs = qs.filter(created_at__gte=since)
        rows, tot = aggregate_usage(qs)
        window = f'last {days} days' if days else 'all time'
        self._render_table(rows, tot, window)

    def _render_table(self, rows, tot, window):
        # 'vendor' leads the row because the ledger groups by vendor AND source:
        # ai_import bills both Anthropic and OpenAI, so without it two different
        # vendors' costs print as two identical-looking 'ai_import' lines.
        self.stdout.write(f'AI usage — {window}')
        header = (
            f'{"vendor":<10}{"source":<12}{"pages":>8}{"in_tok":>12}{"out_tok":>12}'
            f'{"cost_usd":>12}{"$/page":>10}{"100pg":>12}{"500pg":>12}{"1000pg":>12}'
        )
        self.stdout.write(header)
        self.stdout.write('-' * len(header))
        for r in rows:
            pp = r['per_page']
            self.stdout.write(
                f'{r.get("provider", "-"):<10}{r["source"]:<12}{r["pages"]:>8}'
                f'{r["input_tokens"]:>12}'
                f'{r["output_tokens"]:>12}{r["cost"]:>12.4f}{pp:>10.4f}'
                f'{pp * 100:>12.2f}{pp * 500:>12.2f}{pp * 1000:>12.2f}'
            )
        self.stdout.write('-' * len(header))
        tpp = tot['per_page']
        self.stdout.write(
            f'{"TOTAL":<10}{"":<12}{tot["pages"]:>8}{tot["input_tokens"]:>12}'
            f'{tot["output_tokens"]:>12}{tot["cost"]:>12.4f}{tpp:>10.4f}'
            f'{tpp * 100:>12.2f}{tpp * 500:>12.2f}{tpp * 1000:>12.2f}'
        )
        self._render_vendor_totals(tot)

    def _render_vendor_totals(self, tot):
        """Spend per billing vendor — the number an OpenAI bill is checked against."""
        from taskqueue.services import provider_rates

        rates = provider_rates()
        by_provider = tot.get('by_provider') or {}
        self.stdout.write('')
        self.stdout.write('cost by vendor')
        for provider, info in rates.items():
            spend = by_provider.get(provider) or {}
            cost = spend.get('cost', 0)
            if info['input'] is None or info['output'] is None:
                rate = 'rates not configured'
            else:
                rate = f'${info["input"]}/${info["output"]} per Mtok in/out'
            self.stdout.write(
                f'{info["label"]:<20}{cost:>12.4f}   ({rate})'
            )
