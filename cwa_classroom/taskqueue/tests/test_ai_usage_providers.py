"""Per-provider costing in the AI usage ledger (CPP-382).

The ledger used to price every row at Claude's rate, so OpenAI spend — the
ai_import second-opinion verifier — never reached the finance dashboard at all.
These tests pin the behaviour that fixes it, including the deliberate refusal
to guess at an unpriced provider.
"""
from decimal import Decimal

from django.test import TestCase, override_settings

from taskqueue.models import AIUsageLog
from taskqueue.services import UnknownProvider, estimate_cost_usd, record_ai_usage


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class PerProviderCostTests(TestCase):

    def test_anthropic_row_is_priced_at_anthropic_rates(self):
        # 1M in @ $5 + 1M out @ $25
        cost = estimate_cost_usd(1_000_000, 1_000_000,
                                 provider=AIUsageLog.PROVIDER_ANTHROPIC)
        self.assertEqual(cost, Decimal('30.00000'))

    def test_openai_row_is_priced_at_openai_rates(self):
        # 1M in @ $2.50 + 1M out @ $10 — NOT Claude's $30.
        cost = estimate_cost_usd(1_000_000, 1_000_000,
                                 provider=AIUsageLog.PROVIDER_OPENAI)
        self.assertEqual(cost, Decimal('12.50000'))

    def test_provider_defaults_to_anthropic_for_existing_callers(self):
        # Callers that predate the provider argument keep their old behaviour.
        self.assertEqual(estimate_cost_usd(1_000_000, 0),
                         estimate_cost_usd(1_000_000, 0,
                                           provider=AIUsageLog.PROVIDER_ANTHROPIC))

    def test_unknown_provider_is_rejected_not_defaulted(self):
        # Silently pricing an unknown provider at Claude's rate is exactly how
        # OpenAI spend stayed invisible. It must fail loudly instead.
        with self.assertRaises(UnknownProvider):
            estimate_cost_usd(1000, 1000, provider='gemini')


class UnpricedProviderTests(TestCase):

    @override_settings(OPENAI_INPUT_COST_PER_MTOK=None,
                       OPENAI_OUTPUT_COST_PER_MTOK=None)
    def test_unconfigured_openai_rates_raise_rather_than_guess(self):
        with self.assertRaises(UnknownProvider) as ctx:
            estimate_cost_usd(1000, 1000, provider=AIUsageLog.PROVIDER_OPENAI)
        self.assertIn('OPENAI_INPUT_COST_PER_MTOK', str(ctx.exception))

    @override_settings(OPENAI_INPUT_COST_PER_MTOK=None,
                       OPENAI_OUTPUT_COST_PER_MTOK=None)
    def test_recording_an_unpriced_row_does_not_break_the_caller(self):
        # record_ai_usage must never fail work that already succeeded — a
        # missing rate is a configuration problem, not a reason to lose a PDF.
        result = record_ai_usage(
            school=None, provider=AIUsageLog.PROVIDER_OPENAI,
            source=AIUsageLog.SOURCE_AI_IMPORT, session_id=1, pages=1,
            usage={'input_tokens': 100, 'output_tokens': 10})
        self.assertIsNone(result)
        self.assertEqual(AIUsageLog.objects.count(), 0)


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class LedgerRowTests(TestCase):

    def test_rows_record_their_provider(self):
        record_ai_usage(school=None, provider=AIUsageLog.PROVIDER_ANTHROPIC,
                        source=AIUsageLog.SOURCE_AI_IMPORT, session_id=1,
                        pages=2, usage={'input_tokens': 1_000_000,
                                        'output_tokens': 0})
        record_ai_usage(school=None, provider=AIUsageLog.PROVIDER_OPENAI,
                        source=AIUsageLog.SOURCE_AI_IMPORT, session_id=1,
                        pages=2, usage={'input_tokens': 1_000_000,
                                        'output_tokens': 0})

        anthropic = AIUsageLog.objects.get(provider=AIUsageLog.PROVIDER_ANTHROPIC)
        openai = AIUsageLog.objects.get(provider=AIUsageLog.PROVIDER_OPENAI)
        self.assertEqual(anthropic.est_cost_usd, Decimal('5.00000'))
        self.assertEqual(openai.est_cost_usd, Decimal('2.50000'))

    def test_existing_rows_default_to_anthropic(self):
        # The migration backfills historical rows; the model default is what
        # makes that true for anything created without an explicit provider.
        log = AIUsageLog.objects.create(
            source=AIUsageLog.SOURCE_WORKSHEET, pages=1,
            input_tokens=10, output_tokens=1, est_cost_usd=Decimal('0.001'))
        self.assertEqual(log.provider, AIUsageLog.PROVIDER_ANTHROPIC)

    def test_question_review_is_a_recognised_source(self):
        # CPP-380/381 record through this ledger rather than their own field.
        record_ai_usage(school=None, provider=AIUsageLog.PROVIDER_OPENAI,
                        source=AIUsageLog.SOURCE_QUESTION_REVIEW,
                        session_id=None, pages=0,
                        usage={'input_tokens': 500, 'output_tokens': 100})
        self.assertTrue(AIUsageLog.objects.filter(
            source=AIUsageLog.SOURCE_QUESTION_REVIEW).exists())


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class UsageDashboardSplitTests(TestCase):
    """The AI usage dashboard separates vendors (CPP-382)."""

    def _row(self, provider, cost, source=AIUsageLog.SOURCE_AI_IMPORT):
        return AIUsageLog.objects.create(
            provider=provider, source=source, pages=1,
            input_tokens=100, output_tokens=10, est_cost_usd=Decimal(cost))

    def test_same_source_is_split_by_vendor(self):
        # ai_import bills BOTH vendors; one merged row would hide that.
        from taskqueue.dashboard import aggregate_usage

        self._row(AIUsageLog.PROVIDER_ANTHROPIC, '6.00')
        self._row(AIUsageLog.PROVIDER_OPENAI, '1.50')

        rows, _ = aggregate_usage(AIUsageLog.objects.all())
        providers = {r['provider'] for r in rows}
        self.assertEqual(providers, {AIUsageLog.PROVIDER_ANTHROPIC,
                                     AIUsageLog.PROVIDER_OPENAI})
        self.assertEqual(len(rows), 2)

    def test_totals_include_a_per_vendor_breakdown(self):
        from taskqueue.dashboard import aggregate_usage

        self._row(AIUsageLog.PROVIDER_ANTHROPIC, '6.00')
        self._row(AIUsageLog.PROVIDER_OPENAI, '1.50')

        _, totals = aggregate_usage(AIUsageLog.objects.all())
        self.assertEqual(totals['cost'], Decimal('7.50'))
        self.assertEqual(
            totals['by_provider'][AIUsageLog.PROVIDER_OPENAI]['cost'],
            Decimal('1.50'))
        self.assertEqual(
            totals['by_provider'][AIUsageLog.PROVIDER_ANTHROPIC]['cost'],
            Decimal('6.00'))

    def test_markdown_names_the_vendor(self):
        from taskqueue.dashboard import aggregate_usage, render_markdown

        self._row(AIUsageLog.PROVIDER_OPENAI, '1.50')
        rows, totals = aggregate_usage(AIUsageLog.objects.all())
        markdown = render_markdown(rows, totals, window='7d')
        self.assertIn('OpenAI (GPT)', markdown)
        self.assertIn('| Vendor |', markdown)


def _tables(markdown):
    """Split rendered markdown into {header_line: [row_line, ...]} tables."""
    tables, current = {}, None
    for line in markdown.splitlines():
        if not line.startswith('|'):
            current = None
            continue
        if current is None:
            current = line
            tables[current] = []
        elif set(line.replace('|', '').replace(' ', '')) <= set('-:'):
            continue                                    # alignment separator
        else:
            tables[current].append(line)
    return tables


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class TableAlignmentTests(TestCase):
    """Every rendered row lines up with its header (issue #378).

    The published dashboard's totals row was one cell short of the header after
    the Vendor column was added, so GitHub rendered Pages under Source, cost
    under $/page, and so on — every figure shifted one column left.
    """

    def _markdown(self, **kwargs):
        from taskqueue.dashboard import aggregate_usage, render_markdown

        rows, totals = aggregate_usage(AIUsageLog.objects.all())
        return render_markdown(rows, totals, window='last 30 days', **kwargs)

    def _assert_aligned(self, markdown):
        tables = _tables(markdown)
        self.assertTrue(tables, 'no tables rendered')
        for header, body in tables.items():
            width = len(_cells(header))
            for line in body:
                self.assertEqual(
                    len(_cells(line)), width,
                    f'row does not line up with its header\n{header}\n{line}')

    def _log(self, provider, source=AIUsageLog.SOURCE_AI_IMPORT):
        AIUsageLog.objects.create(
            provider=provider, source=source, pages=3,
            input_tokens=1_000, output_tokens=100,
            est_cost_usd=Decimal('1.25'))

    def test_rows_line_up_with_headers(self):
        self._log(AIUsageLog.PROVIDER_ANTHROPIC)
        self._log(AIUsageLog.PROVIDER_OPENAI)
        self._assert_aligned(self._markdown())

    def test_empty_dashboard_rows_line_up(self):
        # The "no usage recorded" placeholder was short a cell too.
        self._assert_aligned(self._markdown())

    def test_grading_table_lines_up(self):
        self._log(AIUsageLog.PROVIDER_ANTHROPIC)
        grading = {'answers': 4, 'tokens': 7_284,
                   'cost': Decimal('0.0338'), 'per_answer': Decimal('0.0084')}
        self._assert_aligned(self._markdown(grading=grading))

    def test_totals_row_keeps_its_figures_under_the_right_headers(self):
        self._log(AIUsageLog.PROVIDER_ANTHROPIC, AIUsageLog.SOURCE_HOMEWORK)
        md = self._markdown()
        header, body = next(
            (h, b) for h, b in _tables(md).items() if '| Vendor | Source |' in h)
        totals = next(line for line in body if '**Total**' in line)
        columns = dict(zip(_cells(header), _cells(totals)))
        self.assertEqual(columns['Vendor'], '**Total**')
        self.assertEqual(columns['Source'], '')
        self.assertEqual(columns['Pages'], '**3**')
        self.assertEqual(columns['Cost (USD)'], '**$1.2500**')

    def test_mis_shaped_row_raises_rather_than_shifting_columns(self):
        from taskqueue.dashboard import _GEN_COLUMNS, _row

        with self.assertRaises(ValueError):
            _row(['only', 'two'], _GEN_COLUMNS)


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class VendorCostSectionTests(TestCase):
    """The dashboard reports OpenAI spend, not just Claude's (issue #378)."""

    def _markdown(self):
        from taskqueue.dashboard import aggregate_usage, render_markdown

        rows, totals = aggregate_usage(AIUsageLog.objects.all())
        return render_markdown(rows, totals, window='last 30 days')

    def _log(self, provider, cost, input_tokens=1_000_000, output_tokens=0):
        AIUsageLog.objects.create(
            provider=provider, source=AIUsageLog.SOURCE_AI_IMPORT, pages=2,
            input_tokens=input_tokens, output_tokens=output_tokens,
            est_cost_usd=Decimal(cost))

    def test_vendor_table_reports_each_vendors_cost(self):
        self._log(AIUsageLog.PROVIDER_ANTHROPIC, '6.00')
        self._log(AIUsageLog.PROVIDER_OPENAI, '2.00')
        md = self._markdown()

        self.assertIn('### Cost by vendor', md)
        rows = {_cells(line)[0]: _cells(line)
                for line in md.splitlines() if line.startswith('| ')}
        self.assertEqual(rows['OpenAI (GPT)'][3], '$2.0000')
        self.assertEqual(rows['Anthropic (Claude)'][3], '$6.0000')
        # Share of total spend: 2 of 8 = 25%.
        self.assertEqual(rows['OpenAI (GPT)'][4], '25.0%')

    def test_vendor_with_no_usage_is_still_listed(self):
        # A missing vendor line reads as "OpenAI cost nothing" — which is how
        # its spend went unnoticed before. Show it at $0 instead.
        self._log(AIUsageLog.PROVIDER_ANTHROPIC, '6.00')
        md = self._markdown()

        self.assertIn('| OpenAI (GPT) |', md)
        openai = next(line for line in md.splitlines()
                      if line.startswith('| OpenAI (GPT) |'))
        self.assertEqual(_cells(openai)[3], '$0.0000')

    def test_vendor_table_names_the_rate_behind_each_cost(self):
        self._log(AIUsageLog.PROVIDER_OPENAI, '2.00')
        md = self._markdown()

        self.assertIn('$2.5 / $10.0', md)      # OpenAI in/out per Mtok
        self.assertIn('$5.0 / $25.0', md)      # Anthropic in/out per Mtok

    def test_rate_line_covers_both_vendors(self):
        md = self._markdown()
        self.assertIn('Anthropic (Claude) $5.0/$25.0 per Mtok in/out', md)
        self.assertIn('OpenAI (GPT) $2.5/$10.0 per Mtok in/out', md)

    @override_settings(OPENAI_INPUT_COST_PER_MTOK=None,
                       OPENAI_OUTPUT_COST_PER_MTOK=None)
    def test_unconfigured_vendor_says_so_rather_than_implying_zero(self):
        md = self._markdown()
        self.assertIn('OpenAI (GPT) rates not configured', md)
        self.assertIn('_not configured_', md)

    @override_settings(OPENAI_INPUT_COST_PER_MTOK=None,
                       OPENAI_OUTPUT_COST_PER_MTOK=None,
                       OPENAI_API_KEY='sk-live')
    def test_active_but_unpriced_vendor_is_flagged_as_uncounted(self):
        # The verifier is running (key set) but its rows can't be priced, so
        # record_ai_usage drops them — a $0 line would be a lie by omission.
        md = self._markdown()
        self.assertIn('OpenAI (GPT) spend is not being counted', md)
        self.assertIn('OPENAI_INPUT_COST_PER_MTOK', md)
        self.assertIn('OPENAI_OUTPUT_COST_PER_MTOK', md)

    @override_settings(OPENAI_INPUT_COST_PER_MTOK=None,
                       OPENAI_OUTPUT_COST_PER_MTOK=None,
                       OPENAI_API_KEY='')
    def test_unused_vendor_is_noted_without_crying_wolf(self):
        md = self._markdown()
        self.assertIn('OpenAI (GPT) is not in use here', md)
        self.assertNotIn('spend is not being counted', md)

    def test_no_warning_when_every_vendor_is_priced(self):
        md = self._markdown()
        self.assertNotIn('⚠️', md)


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class UsageReportCommandVendorTests(TestCase):

    def test_cli_table_names_the_vendor_and_totals_per_vendor(self):
        from io import StringIO

        from django.core.management import call_command

        for provider, cost in ((AIUsageLog.PROVIDER_ANTHROPIC, '6.00'),
                               (AIUsageLog.PROVIDER_OPENAI, '2.00')):
            AIUsageLog.objects.create(
                provider=provider, source=AIUsageLog.SOURCE_AI_IMPORT, pages=2,
                input_tokens=1_000, output_tokens=100,
                est_cost_usd=Decimal(cost))

        out = StringIO()
        call_command('ai_usage_report', stdout=out)
        text = out.getvalue()

        self.assertIn('vendor', text)
        self.assertIn('anthropic', text)
        self.assertIn('openai', text)
        self.assertIn('cost by vendor', text)
        self.assertIn('OpenAI (GPT)', text)
        self.assertIn('2.0000', text)
