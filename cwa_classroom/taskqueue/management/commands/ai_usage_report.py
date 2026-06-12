"""Summarise AI classification usage and cost.

Prints pages, tokens, estimated cost and derived $/page broken down by source
(worksheet / ai_import / homework) over an optional time window — so we can
sanity-check real cost against what we charge.

    python manage.py ai_usage_report --days 30
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from taskqueue.models import AIUsageLog


class Command(BaseCommand):
    help = 'Summarise AI usage and estimated cost by source.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=None,
            help='Only include usage from the last N days (default: all time).',
        )

    def handle(self, *args, **options):
        qs = AIUsageLog.objects.all()
        days = options['days']
        if days:
            since = timezone.now() - timezone.timedelta(days=days)
            qs = qs.filter(created_at__gte=since)
            self.stdout.write(f'AI usage — last {days} days')
        else:
            self.stdout.write('AI usage — all time')

        rows = qs.values('source').annotate(
            pages=Sum('pages'),
            input_tokens=Sum('input_tokens'),
            output_tokens=Sum('output_tokens'),
            cost=Sum('est_cost_usd'),
        ).order_by('source')

        header = f'{"source":<12}{"pages":>8}{"in_tok":>12}{"out_tok":>12}{"cost_usd":>12}{"$/page":>10}'
        self.stdout.write(header)
        self.stdout.write('-' * len(header))

        tot_pages = 0
        tot_in = tot_out = 0
        tot_cost = Decimal('0')
        for r in rows:
            pages = r['pages'] or 0
            cost = r['cost'] or Decimal('0')
            per_page = (cost / pages) if pages else Decimal('0')
            self.stdout.write(
                f'{r["source"]:<12}{pages:>8}{r["input_tokens"] or 0:>12}'
                f'{r["output_tokens"] or 0:>12}{cost:>12.4f}{per_page:>10.4f}'
            )
            tot_pages += pages
            tot_in += r['input_tokens'] or 0
            tot_out += r['output_tokens'] or 0
            tot_cost += cost

        self.stdout.write('-' * len(header))
        tot_per_page = (tot_cost / tot_pages) if tot_pages else Decimal('0')
        self.stdout.write(
            f'{"TOTAL":<12}{tot_pages:>8}{tot_in:>12}{tot_out:>12}'
            f'{tot_cost:>12.4f}{tot_per_page:>10.4f}'
        )
