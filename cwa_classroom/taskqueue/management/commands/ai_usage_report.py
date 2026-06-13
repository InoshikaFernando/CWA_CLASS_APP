"""Summarise AI classification usage and cost.

Prints pages, tokens, estimated cost and derived $/page broken down by source
(worksheet / ai_import / homework) over an optional time window — so we can
sanity-check real cost against what we charge.

    python manage.py ai_usage_report --days 30
    python manage.py ai_usage_report --days 30 --format markdown   # for the dashboard issue
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from taskqueue.models import AIUsageLog


def _aggregate(qs):
    """Return (rows, totals): per-source pages/tokens/cost/$page plus a totals dict."""
    label = dict(AIUsageLog.SOURCE_CHOICES)
    raw = qs.values('source').annotate(
        pages=Sum('pages'),
        input_tokens=Sum('input_tokens'),
        output_tokens=Sum('output_tokens'),
        cost=Sum('est_cost_usd'),
    ).order_by('source')

    rows = []
    tot = {'pages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost': Decimal('0')}
    for r in raw:
        pages = r['pages'] or 0
        cost = r['cost'] or Decimal('0')
        rows.append({
            'source': r['source'],
            'label': label.get(r['source'], r['source']),
            'pages': pages,
            'input_tokens': r['input_tokens'] or 0,
            'output_tokens': r['output_tokens'] or 0,
            'cost': cost,
            'per_page': (cost / pages) if pages else Decimal('0'),
        })
        tot['pages'] += pages
        tot['input_tokens'] += r['input_tokens'] or 0
        tot['output_tokens'] += r['output_tokens'] or 0
        tot['cost'] += cost
    tot['per_page'] = (tot['cost'] / tot['pages']) if tot['pages'] else Decimal('0')
    return rows, tot


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

        rows, tot = _aggregate(qs)
        window = f'last {days} days' if days else 'all time'

        if options['format'] == 'markdown':
            self.stdout.write(self._render_markdown(rows, tot, window))
        else:
            self._render_table(rows, tot, window)

    def _render_table(self, rows, tot, window):
        self.stdout.write(f'AI usage — {window}')
        header = f'{"source":<12}{"pages":>8}{"in_tok":>12}{"out_tok":>12}{"cost_usd":>12}{"$/page":>10}'
        self.stdout.write(header)
        self.stdout.write('-' * len(header))
        for r in rows:
            self.stdout.write(
                f'{r["source"]:<12}{r["pages"]:>8}{r["input_tokens"]:>12}'
                f'{r["output_tokens"]:>12}{r["cost"]:>12.4f}{r["per_page"]:>10.4f}'
            )
        self.stdout.write('-' * len(header))
        self.stdout.write(
            f'{"TOTAL":<12}{tot["pages"]:>8}{tot["input_tokens"]:>12}'
            f'{tot["output_tokens"]:>12}{tot["cost"]:>12.4f}{tot["per_page"]:>10.4f}'
        )

    def _render_markdown(self, rows, tot, window):
        in_rate = getattr(settings, 'CLAUDE_INPUT_COST_PER_MTOK', 3.0)
        out_rate = getattr(settings, 'CLAUDE_OUTPUT_COST_PER_MTOK', 15.0)
        now = timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ')

        lines = [
            '## 🤖 AI Generation Usage',
            '',
            f'_Auto-updated by the `ai-usage-dashboard` workflow • generated `{now}`_',
            f'_Window: **{window}** • cost estimated at ${in_rate}/Mtok in, ${out_rate}/Mtok out_',
            '',
            '| Source | Pages | Input tok | Output tok | Cost (USD) | $/page |',
            '|---|--:|--:|--:|--:|--:|',
        ]
        for r in rows:
            lines.append(
                f'| {r["label"]} | {r["pages"]:,} | {r["input_tokens"]:,} | '
                f'{r["output_tokens"]:,} | ${r["cost"]:.4f} | ${r["per_page"]:.4f} |'
            )
        if not rows:
            lines.append('| _no usage recorded_ | 0 | 0 | 0 | $0.0000 | $0.0000 |')
        lines.append(
            f'| **Total** | **{tot["pages"]:,}** | **{tot["input_tokens"]:,}** | '
            f'**{tot["output_tokens"]:,}** | **${tot["cost"]:.4f}** | **${tot["per_page"]:.4f}** |'
        )
        lines += [
            '',
            '<sub>Source: `AIUsageLog` ledger (worksheet / AI import / homework PDF). '
            'Cost is estimated from token counts, not billed amounts. '
            "This issue is rewritten automatically — don't edit by hand.</sub>",
        ]
        return '\n'.join(lines)
