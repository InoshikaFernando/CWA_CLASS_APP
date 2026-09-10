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
from django.db.models import Count, Sum
from django.utils import timezone

from taskqueue.models import AIUsageLog

logger = logging.getLogger(__name__)

_GITHUB_API = 'https://api.github.com'
_HTTP_TIMEOUT = 5  # seconds — never stall the worker on a slow GitHub.


def aggregate_usage(qs):
    """Return (rows, totals): per-provider-and-source usage plus a totals dict.

    Grouped by provider as well as source because the two vendors are billed
    separately: merging them would report one ai_import cost that is really
    Claude plus GPT, and hide which vendor a rising bill belongs to (CPP-382).
    """
    label = dict(AIUsageLog.SOURCE_CHOICES)
    provider_label = dict(AIUsageLog.PROVIDER_CHOICES)
    raw = qs.values('provider', 'source').annotate(
        pages=Sum('pages'),
        input_tokens=Sum('input_tokens'),
        output_tokens=Sum('output_tokens'),
        cost=Sum('est_cost_usd'),
    ).order_by('provider', 'source')

    rows = []
    tot = {'pages': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost': Decimal('0')}
    for r in raw:
        pages = r['pages'] or 0
        cost = r['cost'] or Decimal('0')
        rows.append({
            'provider': r['provider'],
            'provider_label': provider_label.get(r['provider'], r['provider']),
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
    # Per-vendor spend, so "how much is OpenAI costing us?" is answerable
    # without adding up rows by hand.
    by_provider = {}
    for row in rows:
        entry = by_provider.setdefault(
            row['provider'],
            {'label': row['provider_label'], 'cost': Decimal('0'),
             'input_tokens': 0, 'output_tokens': 0},
        )
        entry['cost'] += row['cost']
        entry['input_tokens'] += row['input_tokens']
        entry['output_tokens'] += row['output_tokens']
    tot['by_provider'] = by_provider
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


def aggregate_question_review(days=None):
    """Sum semantic question review (``maths.QuestionAIReview``) over the window.

    Read from its own table rather than the ``AIUsageLog`` ledger, for two
    reasons that both come down to pricing honestly:

    * it is charged per QUESTION, not per page, so it cannot share the
      page-based table without inventing a $/page for work that has no pages;
    * ``maths.ai_review`` prices each model from ``AI_REVIEW_RATES`` — a cheap
      first pass and a stronger adjudicator, on purpose — while the ledger
      prices a whole provider at one rate. Routing these tokens through the
      ledger would bill a cheap review model at the extraction model's rate,
      which is the same class of error the provider split exists to prevent.

    ``cost`` counts only the reviews whose models had a configured rate;
    ``unpriced`` says how many did not, so an under-reported total is visible
    rather than silent. Returns zeros if nothing was reviewed, or ``None`` if
    the maths app isn't available.
    """
    try:
        from maths.models import QuestionAIReview
    except Exception:
        return None

    qs = QuestionAIReview.objects.all()
    if days:
        qs = qs.filter(reviewed_at__gte=timezone.now() - timezone.timedelta(days=days))

    agg = qs.aggregate(
        reviews=Count('id'),
        input_tokens=Sum('input_tokens'),
        output_tokens=Sum('output_tokens'),
        cost=Sum('cost_usd'),
    )
    reviews = agg['reviews'] or 0
    cost = agg['cost'] or Decimal('0')
    return {
        'reviews': reviews,
        'escalated': qs.filter(escalated=True).count(),
        'input_tokens': agg['input_tokens'] or 0,
        'output_tokens': agg['output_tokens'] or 0,
        'cost': cost,
        'per_review': (cost / reviews) if reviews else Decimal('0'),
        'unpriced': qs.filter(cost_usd__isnull=True).count(),
    }


# Column headers for the generation table, with their alignment. Kept as data
# and rendered through ``_row`` so every line — data, empty state, totals —
# is built against the same column count: the totals row silently lost its
# Source cell when the Vendor column was added (CPP-382), which shifted every
# figure in it one column left on the published issue.
_GEN_COLUMNS = (
    ('Vendor', '---'), ('Source', '---'), ('Pages', '--:'),
    ('Input tok', '--:'), ('Output tok', '--:'), ('Cost (USD)', '--:'),
    ('$/page', '--:'), ('100 pages', '--:'), ('500 pages', '--:'),
    ('1000 pages', '--:'),
)

_GRADING_COLUMNS = (
    ('Answers graded', '--:'), ('Tokens', '--:'), ('Cost (USD)', '--:'),
    ('$/answer', '--:'),
)

_REVIEW_COLUMNS = (
    ('Questions reviewed', '--:'), ('Escalated', '--:'), ('Input tok', '--:'),
    ('Output tok', '--:'), ('Cost (USD)', '--:'), ('$/question', '--:'),
)

_VENDOR_COLUMNS = (
    ('Vendor', '---'), ('Input tok', '--:'), ('Output tok', '--:'),
    ('Cost (USD)', '--:'), ('Share', '--:'), ('Rate in / out ($/Mtok)', '---'),
)


def _row(cells, columns):
    """Render one markdown table row, refusing to emit a mis-shaped one.

    A row with the wrong number of cells doesn't fail — GitHub renders it,
    shifted, and the numbers silently line up under the wrong headers. Raising
    turns that into a test failure instead. Callers of the dashboard already
    swallow their own errors, so this can never fail an AI call.
    """
    cells = list(cells)
    if len(cells) != len(columns):
        raise ValueError(
            f'Table row has {len(cells)} cells but the table has '
            f'{len(columns)} columns: {cells!r}')
    return '| ' + ' | '.join(cells) + ' |'


def _header(columns):
    return [
        _row([name for name, _ in columns], columns),
        '|' + '|'.join(align for _, align in columns) + '|',
    ]


def _rate_summary(rates):
    """One line naming each vendor's configured $/Mtok rates."""
    parts = []
    for info in rates.values():
        if info['input'] is None or info['output'] is None:
            parts.append(f'{info["label"]} rates not configured')
        else:
            parts.append(
                f'{info["label"]} ${info["input"]}/${info["output"]} per Mtok in/out')
    return ' • '.join(parts)


def _render_vendor_table(tot, rates):
    """Cost split by vendor — Anthropic vs OpenAI — for the window.

    Every priced vendor gets a line even with no usage: OpenAI's second-opinion
    spend was invisible for as long as the dashboard only ever showed one
    vendor, and a vendor missing from the table is indistinguishable from a
    vendor that cost nothing. Rows with usage but no configured rate are
    impossible (``estimate_cost_usd`` refuses to price them), so an unpriced
    vendor shows $0.0000 and says its rates are unset.
    """
    by_provider = tot.get('by_provider') or {}
    total_cost = tot['cost']
    providers = list(rates) + [p for p in by_provider if p not in rates]

    lines = ['', '### Cost by vendor', '', *_header(_VENDOR_COLUMNS)]
    for provider in providers:
        info = rates.get(provider, {})
        spend = by_provider.get(provider) or {
            'label': info.get('label', provider), 'cost': Decimal('0'),
            'input_tokens': 0, 'output_tokens': 0,
        }
        cost = spend['cost']
        share = (cost / total_cost * 100) if total_cost else Decimal('0')
        if info.get('input') is None or info.get('output') is None:
            rate = '_not configured_'
        else:
            rate = f'${info["input"]} / ${info["output"]}'
        lines.append(_row([
            spend.get('label', provider), f'{spend["input_tokens"]:,}',
            f'{spend["output_tokens"]:,}', f'${cost:.4f}', f'{share:.1f}%', rate,
        ], _VENDOR_COLUMNS))

    lines.append(_row([
        '**Total**',
        f'**{tot["input_tokens"]:,}**', f'**{tot["output_tokens"]:,}**',
        f'**${total_cost:.4f}**', '**100.0%**' if total_cost else '**0.0%**', '',
    ], _VENDOR_COLUMNS))
    lines += _unpriced_vendor_warnings(rates)
    return lines


# A vendor is "wired up" when the pipeline that bills it is switched on. Only
# OpenAI has such a switch — Anthropic is always in use.
_PROVIDER_ENABLED_SETTING = {AIUsageLog.PROVIDER_OPENAI: 'OPENAI_API_KEY'}


def _unpriced_vendor_warnings(rates):
    """Say out loud when a vendor's spend can't be priced — and is being lost.

    An unpriced row isn't recorded at all: ``estimate_cost_usd`` raises and
    ``record_ai_usage`` swallows it so a successful PDF never fails, which means
    the call vanishes from the ledger. Showing that vendor as a quiet $0 would
    report "OpenAI costs nothing" when the truth is "we aren't counting OpenAI"
    — so the dashboard names the missing settings instead.
    """
    lines = []
    for provider, info in rates.items():
        if info['input'] is not None and info['output'] is not None:
            continue
        setting = _PROVIDER_ENABLED_SETTING.get(provider)
        active = bool(getattr(settings, setting, '')) if setting else True
        fix = (f'set `{info["input_setting"]}` and `{info["output_setting"]}` '
               '(USD per million tokens) in the environment file')
        if active:
            lines.append(
                f'> ⚠️ **{info["label"]} spend is not being counted.** Its calls '
                f'are running but cannot be priced, so they are dropped from the '
                f'ledger entirely and every total above understates real cost — '
                f'{fix}.')
        else:
            lines.append(
                f'> ℹ️ {info["label"]} is not in use here and has no rates '
                f'configured. To start counting it, {fix}.')
    return ['', *lines] if lines else []


def render_markdown(rows, tot, window, *, generated_at=None, grading=None,
                    review=None, env_label=None):
    """Render the GitHub-flavoured dashboard (page-based generation + grading).

    ``env_label`` sets the heading — when given (e.g. "🏭 Production") this block
    is one environment's section of a shared issue; otherwise it's a standalone
    dashboard.
    """
    from taskqueue.services import provider_rates

    rates = provider_rates()
    now = (generated_at or timezone.now()).strftime('%Y-%m-%dT%H:%M:%SZ')

    lines = [
        f'## {env_label}' if env_label else '## 🤖 AI Generation Usage',
        '',
        f'_Auto-updated after each AI call • last update `{now}`_',
        f'_Window: **{window}** • cost estimated at {_rate_summary(rates)}_',
        '',
        '### Generation & classification (per page)',
        '',
        *_header(_GEN_COLUMNS),
    ]
    for r in rows:
        pp = r['per_page']
        lines.append(_row([
            # .get: render_markdown takes plain dicts and is called with
            # hand-built rows elsewhere; a missing vendor must not break it.
            r.get('provider_label', '—'), r['label'], f'{r["pages"]:,}',
            f'{r["input_tokens"]:,}', f'{r["output_tokens"]:,}',
            f'${r["cost"]:.4f}', f'${pp:.4f}',
            f'${pp * 100:.2f}', f'${pp * 500:.2f}', f'${pp * 1000:.2f}',
        ], _GEN_COLUMNS))
    if not rows:
        lines.append(_row(
            ['_no usage recorded_', '—', '0', '0', '0',
             '$0.0000', '$0.0000', '$0.00', '$0.00', '$0.00'],
            _GEN_COLUMNS))
    tpp = tot['per_page']
    lines.append(_row([
        '**Total**', '', f'**{tot["pages"]:,}**', f'**{tot["input_tokens"]:,}**',
        f'**{tot["output_tokens"]:,}**', f'**${tot["cost"]:.4f}**', f'**${tpp:.4f}**',
        f'**${tpp * 100:.2f}**', f'**${tpp * 500:.2f}**', f'**${tpp * 1000:.2f}**',
    ], _GEN_COLUMNS))

    lines += _render_vendor_table(tot, rates)

    grand_total = tot['cost']
    if grading is not None:
        grand_total += grading['cost']
        lines += [
            '',
            '### AI grading (per answer)',
            '',
            *_header(_GRADING_COLUMNS),
            _row([f'{grading["answers"]:,}', f'{grading["tokens"]:,}',
                  f'${grading["cost"]:.4f}', f'${grading["per_answer"]:.4f}'],
                 _GRADING_COLUMNS),
        ]

    if review is not None and review['reviews']:
        grand_total += review['cost']
        unpriced = ''
        if review['unpriced']:
            unpriced = (f' — {review["unpriced"]:,} of these had no configured '
                        f'model rate, so the cost above is a floor')
        lines += [
            '',
            '### Question review (per question)',
            '',
            *_header(_REVIEW_COLUMNS),
            _row([f'{review["reviews"]:,}', f'{review["escalated"]:,}',
                  f'{review["input_tokens"]:,}', f'{review["output_tokens"]:,}',
                  f'${review["cost"]:.4f}', f'${review["per_review"]:.4f}'],
                 _REVIEW_COLUMNS),
        ]
        if unpriced:
            lines += ['', f'_{unpriced.lstrip(" —")}_']

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
    if review is not None and review['reviews']:
        footnote += (
            'Question review from `maths.QuestionAIReview` (per question, priced '
            'per model from AI_REVIEW_RATES rather than at a whole provider\'s '
            'rate, because it deliberately runs a cheap pass and a stronger '
            'adjudicator). '
        )
    footnote += (
        'Cost by vendor splits the same generation ledger by billing vendor, '
        'each priced at its own configured rate. Costs are estimated from token '
        'counts at list price, not billed amounts. This issue is rewritten '
        "automatically — don't edit by hand."
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
    review = aggregate_question_review(days)
    return render_markdown(rows, tot, window, generated_at=generated_at,
                           grading=grading, review=review, env_label=env_label)


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
