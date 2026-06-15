"""Shared AI-usage dashboard logic: aggregate the ledger, render the markdown,
and (best-effort) push it to a pinned GitHub issue after each AI call.

The markdown here is the single source of truth for both the
``ai_usage_report --format markdown`` command (used by the daily workflow) and
the live, per-call refresh triggered from ``record_ai_usage``.

The live refresh is intentionally fire-and-forget: it never raises into the
caller and stays a no-op until ``AI_DASHBOARD_GITHUB_TOKEN`` and
``AI_DASHBOARD_GITHUB_REPO`` are set, so dev / test / local never call out.
"""
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from taskqueue.models import AIUsageLog

logger = logging.getLogger(__name__)

_GITHUB_API = 'https://api.github.com'
_HTTP_TIMEOUT = 5  # seconds — never stall the worker on a slow GitHub.


def aggregate_usage(qs):
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


def aggregate_grading(days=None):
    """Sum AI grading usage (``billing.AIGradingUsage``) over the window.

    Grading is logged to a separate ledger (per school, per billing month), so
    the window is applied at month granularity — any billing month overlapping
    the last ``days``. Returns a dict (zeros if no rows), or ``None`` if the
    billing model isn't available.
    """
    try:
        from billing.models import AIGradingUsage
    except Exception:
        return None
    qs = AIGradingUsage.objects.all()
    if days:
        since_month = (timezone.now() - timezone.timedelta(days=days)).date().replace(day=1)
        qs = qs.filter(period_start__gte=since_month)
    agg = qs.aggregate(
        answers=Sum('answers_graded'),
        tokens=Sum('tokens_used'),
        cost=Sum('estimated_cost_usd'),
    )
    answers = agg['answers'] or 0
    cost = agg['cost'] or Decimal('0')
    return {
        'answers': answers,
        'tokens': agg['tokens'] or 0,
        'cost': cost,
        'per_answer': (cost / answers) if answers else Decimal('0'),
    }


def render_markdown(rows, tot, window, *, generated_at=None, grading=None, env_label=None):
    """Render the GitHub-flavoured dashboard (page-based generation + grading).

    ``env_label`` sets the heading — when given (e.g. "🏭 Production") this block
    is one environment's section of a shared issue; otherwise it's a standalone
    dashboard.
    """
    in_rate = getattr(settings, 'CLAUDE_INPUT_COST_PER_MTOK', 3.0)
    out_rate = getattr(settings, 'CLAUDE_OUTPUT_COST_PER_MTOK', 15.0)
    now = (generated_at or timezone.now()).strftime('%Y-%m-%dT%H:%M:%SZ')

    lines = [
        f'## {env_label}' if env_label else '## 🤖 AI Generation Usage',
        '',
        f'_Auto-updated after each AI call • last update `{now}`_',
        f'_Window: **{window}** • cost estimated at ${in_rate}/Mtok in, ${out_rate}/Mtok out_',
        '',
        '### Generation & classification (per page)',
        '',
        '| Source | Pages | Input tok | Output tok | Cost (USD) | $/page | '
        '100 pages | 500 pages | 1000 pages |',
        '|---|--:|--:|--:|--:|--:|--:|--:|--:|',
    ]
    for r in rows:
        pp = r['per_page']
        lines.append(
            f'| {r["label"]} | {r["pages"]:,} | {r["input_tokens"]:,} | '
            f'{r["output_tokens"]:,} | ${r["cost"]:.4f} | ${pp:.4f} | '
            f'${pp * 100:.2f} | ${pp * 500:.2f} | ${pp * 1000:.2f} |'
        )
    if not rows:
        lines.append('| _no usage recorded_ | 0 | 0 | 0 | $0.0000 | $0.0000 | $0.00 | $0.00 | $0.00 |')
    tpp = tot['per_page']
    lines.append(
        f'| **Total** | **{tot["pages"]:,}** | **{tot["input_tokens"]:,}** | '
        f'**{tot["output_tokens"]:,}** | **${tot["cost"]:.4f}** | **${tpp:.4f}** | '
        f'**${tpp * 100:.2f}** | **${tpp * 500:.2f}** | **${tpp * 1000:.2f}** |'
    )

    grand_total = tot['cost']
    if grading is not None:
        grand_total += grading['cost']
        lines += [
            '',
            '### AI grading (per answer)',
            '',
            '| Answers graded | Tokens | Cost (USD) | $/answer |',
            '|--:|--:|--:|--:|',
            f'| {grading["answers"]:,} | {grading["tokens"]:,} | '
            f'${grading["cost"]:.4f} | ${grading["per_answer"]:.4f} |',
        ]

    lines += [
        '',
        f'### 💰 Total AI cost — **${grand_total:.4f}**',
    ]

    footnote = (
        'Generation / classification from the `AIUsageLog` ledger (page-based). '
    )
    if grading is not None:
        footnote += (
            'AI grading from `billing.AIGradingUsage` (per answer, bucketed by '
            'billing month, so its window is approximate). '
        )
    footnote += (
        'Costs are estimated from token counts at list price, not billed '
        "amounts. This issue is rewritten automatically — don't edit by hand."
    )
    lines += ['', f'<sub>{footnote}</sub>']
    return '\n'.join(lines)


def build_usage_markdown(days=None, generated_at=None, env_label=None):
    """Aggregate both ledgers over the last ``days`` and render the dashboard."""
    qs = AIUsageLog.objects.all()
    if days:
        since = timezone.now() - timezone.timedelta(days=days)
        qs = qs.filter(created_at__gte=since)
    rows, tot = aggregate_usage(qs)
    window = f'last {days} days' if days else 'all time'
    grading = aggregate_grading(days)
    return render_markdown(rows, tot, window, generated_at=generated_at,
                           grading=grading, env_label=env_label)


# --- per-environment sections -------------------------------------------------
# Prod / test / dev all publish to ONE issue; each owns a named section so they
# never clobber each other. The section key (the env name) drives both the
# HTML-comment markers and the heading.

_ENV_EMOJI = {'production': '🏭', 'prod': '🏭', 'test': '🧪',
              'others': '🗂️', 'other': '🗂️', 'dev': '🛠️', 'development': '🛠️'}


def _section_heading(env):
    """'Production' → '🏭 Production' (falls back to a generic icon)."""
    return f'{_ENV_EMOJI.get(env.lower(), "📊")} {env}'


def _merge_section(existing_body, env, section_md):
    """Replace this env's marked block in ``existing_body`` (append if absent)."""
    import re
    start = f'<!-- AIDASH:{env}:START -->'
    end = f'<!-- AIDASH:{env}:END -->'
    block = f'{start}\n{section_md}\n{end}'
    existing_body = existing_body or ''
    if start in existing_body and end in existing_body:
        pattern = re.escape(start) + r'.*?' + re.escape(end)
        return re.sub(pattern, lambda _m: block, existing_body, flags=re.DOTALL)

    title = '# 🤖 AI Generation Usage'
    if title in existing_body:
        return existing_body.rstrip() + '\n\n' + block + '\n'
    intro = (
        f'{title}\n\n_Per-environment AI usage & cost — each section is rewritten '
        "automatically by its own environment. Don't edit by hand._\n\n"
    )
    return intro + block + '\n'


def _resolve_issue_number(repo, headers):
    """Return the dashboard issue number — from settings, else the labelled issue."""
    configured = getattr(settings, 'AI_DASHBOARD_ISSUE_NUMBER', '')
    if configured:
        return str(configured).strip()
    label = getattr(settings, 'AI_DASHBOARD_ISSUE_LABEL', 'ai-usage-dashboard')
    resp = requests.get(
        f'{_GITHUB_API}/repos/{repo}/issues',
        params={'labels': label, 'state': 'open', 'per_page': 1},
        headers=headers, timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    issues = resp.json()
    return str(issues[0]['number']) if issues else None


def update_dashboard_issue(days=None):
    """Best-effort: rewrite the pinned GitHub issue with the latest usage.

    Returns True if the issue was updated, False if disabled/skipped. Never
    raises — usage accounting and the AI call must not fail because GitHub is
    slow or misconfigured.
    """
    token = getattr(settings, 'AI_DASHBOARD_GITHUB_TOKEN', '')
    repo = getattr(settings, 'AI_DASHBOARD_GITHUB_REPO', '')
    if not token or not repo:
        # Not configured (dev / test / local) — silently stay idle.
        return False

    if days is None:
        days = getattr(settings, 'AI_USAGE_WINDOW_DAYS', 30)

    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    # This environment owns one named section (default "Others"). It reads the
    # current issue, swaps in only its block, and writes back — so prod / test /
    # dev share one issue without overwriting each other.
    env = (getattr(settings, 'AI_DASHBOARD_ENV', '') or '').strip() or 'Others'

    try:
        number = _resolve_issue_number(repo, headers)
        if not number:
            logger.warning(
                'AI dashboard: no open issue with label %r in %s — skipping update.',
                getattr(settings, 'AI_DASHBOARD_ISSUE_LABEL', 'ai-usage-dashboard'), repo,
            )
            return False

        issue_url = f'{_GITHUB_API}/repos/{repo}/issues/{number}'
        cur = requests.get(issue_url, headers=headers, timeout=_HTTP_TIMEOUT)
        cur.raise_for_status()
        existing_body = cur.json().get('body') or ''

        section = build_usage_markdown(days=days, env_label=_section_heading(env))
        body = _merge_section(existing_body, env, section)

        resp = requests.patch(
            issue_url, json={'body': body},
            headers=headers, timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info('AI dashboard: refreshed %r section of issue #%s in %s',
                    env, number, repo)
        return True
    except Exception:
        logger.exception('AI dashboard: live refresh failed (non-fatal)')
        return False
