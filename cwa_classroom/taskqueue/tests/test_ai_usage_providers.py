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
