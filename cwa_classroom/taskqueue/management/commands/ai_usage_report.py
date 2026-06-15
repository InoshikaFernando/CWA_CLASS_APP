"""Summarise AI classification usage and cost.

Prints pages, tokens, estimated cost and derived $/page broken down by source
(worksheet / ai_import / homework) over an optional time window — so we can
sanity-check real cost against what we charge.

    python manage.py ai_usage_report --days 30
    python manage.py ai_usage_report --days 30 --format markdown   # for the dashboard issue
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from taskqueue.dashboard import aggregate_usage, render_markdown
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
        qs = AIUsageLog.objects.all()
        days = options['days']
        if days:
            since = timezone.now() - timezone.timedelta(days=days)
            qs = qs.filter(created_at__gte=since)

        rows, tot = aggregate_usage(qs)
        window = f'last {days} days' if days else 'all time'

        if options['format'] == 'markdown':
            self.stdout.write(render_markdown(rows, tot, window))
        else:
            self._render_table(rows, tot, window)

    def _render_table(self, rows, tot, window):
        self.stdout.write(f'AI usage — {window}')
        header = (
            f'{"source":<12}{"pages":>8}{"in_tok":>12}{"out_tok":>12}{"cost_usd":>12}'
            f'{"$/page":>10}{"100pg":>12}{"500pg":>12}{"1000pg":>12}'
        )
        self.stdout.write(header)
        self.stdout.write('-' * len(header))
        for r in rows:
            pp = r['per_page']
            self.stdout.write(
                f'{r["source"]:<12}{r["pages"]:>8}{r["input_tokens"]:>12}'
                f'{r["output_tokens"]:>12}{r["cost"]:>12.4f}{pp:>10.4f}'
                f'{pp * 100:>12.2f}{pp * 500:>12.2f}{pp * 1000:>12.2f}'
            )
        self.stdout.write('-' * len(header))
        tpp = tot['per_page']
        self.stdout.write(
            f'{"TOTAL":<12}{tot["pages"]:>8}{tot["input_tokens"]:>12}'
            f'{tot["output_tokens"]:>12}{tot["cost"]:>12.4f}{tpp:>10.4f}'
            f'{tpp * 100:>12.2f}{tpp * 500:>12.2f}{tpp * 1000:>12.2f}'
        )
