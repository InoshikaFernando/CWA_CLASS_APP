"""Tests for the AI usage / cost ledger (taskqueue.services.record_ai_usage)."""
from decimal import Decimal

import pytest
from django.core.management import call_command

from taskqueue.models import AIUsageLog
from taskqueue.services import estimate_cost_usd, record_ai_usage

pytestmark = pytest.mark.django_db


def test_estimate_cost_uses_default_rates():
    # 1M input @ $3 + 1M output @ $15 = $18.
    assert estimate_cost_usd(1_000_000, 1_000_000) == Decimal('18.00000')
    # Half a million output only @ $15 = $7.50.
    assert estimate_cost_usd(0, 500_000) == Decimal('7.50000')
    assert estimate_cost_usd(0, 0) == Decimal('0.00000')


def test_estimate_cost_honours_settings(settings):
    settings.CLAUDE_INPUT_COST_PER_MTOK = 1.0
    settings.CLAUDE_OUTPUT_COST_PER_MTOK = 2.0
    assert estimate_cost_usd(1_000_000, 1_000_000) == Decimal('3.00000')


def test_record_ai_usage_creates_row_with_cost():
    log = record_ai_usage(
        school=None,
        source=AIUsageLog.SOURCE_WORKSHEET,
        session_id=42,
        pages=13,
        usage={'input_tokens': 30_000, 'output_tokens': 15_000, 'total_tokens': 45_000},
    )
    assert log.pk is not None
    assert log.source == 'worksheet'
    assert log.pages == 13
    assert log.input_tokens == 30_000
    assert log.output_tokens == 15_000
    assert log.total_tokens == 45_000
    # 30k in @ $3/M + 15k out @ $15/M = 0.09 + 0.225 = 0.315
    assert log.est_cost_usd == Decimal('0.31500')
    # $0.315 / 13 pages.
    assert log.cost_per_page_usd == Decimal('0.31500') / 13


def test_record_ai_usage_handles_missing_tokens():
    log = record_ai_usage(
        school=None, source=AIUsageLog.SOURCE_AI_IMPORT,
        session_id=1, pages=2, usage={},
    )
    assert log.input_tokens == 0
    assert log.output_tokens == 0
    assert log.est_cost_usd == Decimal('0.00000')


def test_record_ai_usage_never_raises(monkeypatch):
    # Even if the create blows up, the caller (a successful PDF) must not fail.
    def boom(*a, **k):
        raise RuntimeError('db down')
    monkeypatch.setattr(AIUsageLog.objects, 'create', boom)
    assert record_ai_usage(
        school=None, source='worksheet', session_id=1, pages=1, usage={},
    ) is None


def test_cost_per_page_none_when_zero_pages():
    log = record_ai_usage(
        school=None, source='homework', session_id=1, pages=0,
        usage={'input_tokens': 100, 'output_tokens': 100},
    )
    assert log.cost_per_page_usd is None


def test_usage_report_command_runs():
    record_ai_usage(
        school=None, source='worksheet', session_id=1, pages=10,
        usage={'input_tokens': 20_000, 'output_tokens': 10_000},
    )
    record_ai_usage(
        school=None, source='ai_import', session_id=2, pages=5,
        usage={'input_tokens': 10_000, 'output_tokens': 5_000},
    )
    # Should not raise and should aggregate both sources.
    call_command('ai_usage_report')
    call_command('ai_usage_report', '--days', '7')


def test_usage_report_markdown_includes_cost_per_page():
    from io import StringIO

    # worksheet: 20k in + 10k out = $0.06 + $0.15 = $0.21 over 10 pages -> $0.021/page
    record_ai_usage(
        school=None, source='worksheet', session_id=1, pages=10,
        usage={'input_tokens': 20_000, 'output_tokens': 10_000},
    )
    out = StringIO()
    call_command('ai_usage_report', '--format', 'markdown', stdout=out)
    md = out.getvalue()

    # Markdown table with a $/page column, page-cost projections and a totals row.
    assert (
        '| Source | Pages | Input tok | Output tok | Cost (USD) | $/page | '
        '100 pages | 500 pages | 1000 pages |'
    ) in md
    assert '| Worksheet |' in md
    assert '**Total**' in md
    assert '$0.0210' in md          # $/page for the single source
    assert '$2.10' in md            # 100-page projection ($0.021 * 100)
    assert '$10.50' in md           # 500-page projection ($0.021 * 500)
    assert '$21.00' in md           # 1000-page projection ($0.021 * 1000)
    assert 'AI Generation Usage' in md


def test_usage_report_markdown_handles_no_data():
    from io import StringIO

    out = StringIO()
    call_command('ai_usage_report', '--days', '1', '--format', 'markdown', stdout=out)
    md = out.getvalue()
    assert 'no usage recorded' in md
    assert '**Total**' in md


# --- live GitHub dashboard refresh ------------------------------------------

class _FakeResp:
    def __init__(self, payload=None, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def test_dashboard_update_noop_when_unconfigured(settings, monkeypatch):
    from taskqueue import dashboard

    # No token/repo → must not touch the network.
    settings.AI_DASHBOARD_GITHUB_TOKEN = ''
    settings.AI_DASHBOARD_GITHUB_REPO = ''
    called = []
    monkeypatch.setattr(dashboard.requests, 'get', lambda *a, **k: called.append('get'))
    monkeypatch.setattr(dashboard.requests, 'patch', lambda *a, **k: called.append('patch'))

    assert dashboard.update_dashboard_issue() is False
    assert called == []


def test_dashboard_update_patches_issue_when_configured(settings, monkeypatch):
    from taskqueue import dashboard

    settings.AI_DASHBOARD_GITHUB_TOKEN = 'tok'
    settings.AI_DASHBOARD_GITHUB_REPO = 'owner/repo'
    settings.AI_DASHBOARD_ISSUE_NUMBER = ''        # force label lookup
    settings.AI_DASHBOARD_ISSUE_LABEL = 'ai-usage-dashboard'

    # Mock the network up front — record_ai_usage now triggers a refresh itself.
    seen = {}
    monkeypatch.setattr(
        dashboard.requests, 'get',
        lambda url, **k: _FakeResp(payload=[{'number': 378}]),
    )

    def fake_patch(url, **kwargs):
        seen['url'] = url
        seen['body'] = kwargs['json']['body']
        return _FakeResp(payload={})
    monkeypatch.setattr(dashboard.requests, 'patch', fake_patch)

    record_ai_usage(
        school=None, source='homework', session_id=1, pages=4,
        usage={'input_tokens': 8_000, 'output_tokens': 4_000},
    )

    assert dashboard.update_dashboard_issue() is True
    assert seen['url'].endswith('/repos/owner/repo/issues/378')
    assert 'AI Generation Usage' in seen['body']
    assert '| Homework PDF |' in seen['body']


def test_dashboard_update_never_raises_on_http_error(settings, monkeypatch):
    from taskqueue import dashboard

    settings.AI_DASHBOARD_GITHUB_TOKEN = 'tok'
    settings.AI_DASHBOARD_GITHUB_REPO = 'owner/repo'

    def boom(*a, **k):
        raise RuntimeError('github down')
    monkeypatch.setattr(dashboard.requests, 'get', boom)

    # Must swallow the error and report failure, not propagate.
    assert dashboard.update_dashboard_issue() is False


def test_record_ai_usage_triggers_dashboard_refresh(monkeypatch):
    import taskqueue.dashboard as dashboard

    calls = []
    monkeypatch.setattr(dashboard, 'update_dashboard_issue', lambda *a, **k: calls.append(1))

    record_ai_usage(
        school=None, source='worksheet', session_id=7, pages=3,
        usage={'input_tokens': 1_000, 'output_tokens': 500},
    )
    assert calls == [1]
