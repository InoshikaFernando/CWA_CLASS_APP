"""Fetch what the AI vendors actually billed (CPP-383).

AI cost used to be estimated as ``tokens x a rate in config``. Rates go stale
silently — this codebase already lost 67% of its AI cost that way when the
model changed and the rate did not (see the note in ``taskqueue/services.py``).
Every other vendor's cost is fetched, not guessed: ``sync_digitalocean_expenses``
pulls real DigitalOcean invoices. This module does the same for the AI vendors.

Each provider exposes an admin/billing API, separate from the inference API:

  Anthropic  GET /v1/organizations/cost_report
             x-api-key: an Admin API key (sk-ant-admin...), created by an
             organization admin in the Console. Distinct from ANTHROPIC_API_KEY.

  OpenAI     GET https://api.openai.com/v1/organization/costs
             Authorization: Bearer <Admin API key>, created by an organization
             Owner. Admin keys cannot call models, and model keys cannot read
             costs — so this genuinely needs its own credential.

Both are self-gating: with no admin key configured the fetch returns None and
the caller records nothing, rather than falling back to an estimate. A missing
figure must look missing.

Both responses have been verified against live API calls, and the fixtures in
``billing/tests_ai_vendor_costs.py`` are copied from those real payloads.

Both endpoints PAGINATE (``has_more`` / ``next_page``). Following that is not
optional: a month-long window returns more buckets than one page holds, and
reading only the first page would silently report a fraction of the real spend
— the exact failure this module exists to prevent.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ANTHROPIC_COST_URL = 'https://api.anthropic.com/v1/organizations/cost_report'
OPENAI_COST_URL = 'https://api.openai.com/v1/organization/costs'

ANTHROPIC_VERSION = '2023-06-01'
REQUEST_TIMEOUT = 30

# A month of daily buckets fits well inside this; the cap only stops a runaway
# cursor loop. Hitting it means something is wrong, so it raises rather than
# returning a partial total.
MAX_PAGES = 50

# What one unit of a provider's `amount` is worth in USD. NOT a shared
# assumption — the providers differ, and getting it wrong is a 100x error in
# the accounts, which is the whole failure mode this module exists to avoid.
#
#   anthropic: CENTS. Verified 2026-08-17 — the cost report returned 2470.232
#     for 10-16 Aug while the Console showed $41.49 spent for the whole month.
#     As dollars that single week would be 60x the month; as cents it is
#     $24.70, which fits.
#
#   openai: assumed DOLLARS, from the documented {value, currency} shape. NOT
#     yet verified against real data — every bucket came back empty because
#     nothing had been billed. Re-check this the first time a non-zero OpenAI
#     figure appears; until then it scales 0 either way and cannot be wrong.
AMOUNT_TO_USD = {
    'anthropic': Decimal('0.01'),
    'openai': Decimal('1'),
}


class VendorCostUnavailable(Exception):
    """The vendor's billed figure could not be obtained.

    Raised rather than returning zero: a period with no data must be reported
    as unknown, never as free.
    """


@dataclass(frozen=True)
class DailyCost:
    """One day's billed spend with one vendor, in USD."""
    on: date
    amount_usd: Decimal


# --------------------------------------------------------------------------
# Response parsing — the part that needs verifying against a real response
# --------------------------------------------------------------------------
def _money(entry):
    """Coerce one cost entry to a Decimal USD amount, or raise.

    Anthropic returns ``{"currency": "USD", "amount": "326.237", ...}`` — the
    amount is a *string* and the currency is its *sibling*. OpenAI nests
    ``{"amount": {"value": .., "currency": ..}}``. Both are handled, and the
    currency is checked wherever it appears: converting a non-USD figure as if
    it were dollars would be a silently wrong number in the accounts.
    """
    currency = None
    value = entry

    if isinstance(entry, dict):
        currency = entry.get('currency')
        value = entry.get('amount', entry.get('value'))
        if isinstance(value, dict):                 # OpenAI's nested form
            currency = value.get('currency', currency)
            value = value.get('value', value.get('amount'))

    if currency is not None and str(currency).lower() != 'usd':
        raise VendorCostUnavailable(f'Expected USD amounts, got {currency!r}')
    if value is None:
        raise VendorCostUnavailable('Cost entry has no amount')
    try:
        return Decimal(str(value))
    except Exception as exc:                                   # noqa: BLE001
        raise VendorCostUnavailable(f'Unreadable amount {value!r}') from exc


def _bucket_date(bucket):
    """Read a bucket's start as a date, accepting epoch seconds or ISO."""
    raw = (bucket.get('start_time') or bucket.get('starting_at')
           or bucket.get('start') or bucket.get('date'))
    if raw is None:
        raise VendorCostUnavailable('Cost bucket has no start time')
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=dt_timezone.utc).date()
    text = str(raw).replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise VendorCostUnavailable(f'Unreadable bucket start {raw!r}') from exc


def _extract_daily_costs(payload, scale=Decimal('1')):
    """Pull [DailyCost] out of a bucketed cost response.

    Both providers return time buckets each holding cost entries; the entries
    are summed per bucket and multiplied by ``scale`` to reach USD. The scale
    is the caller's because the providers do not agree on units — see
    AMOUNT_TO_USD.
    """
    buckets = payload.get('data')
    if buckets is None:
        raise VendorCostUnavailable(
            f'No "data" in cost response (keys: {sorted(payload)})')

    costs = []
    for bucket in buckets:
        on = _bucket_date(bucket)
        entries = bucket.get('results', bucket.get('items', []))
        total = sum((_money(entry) for entry in entries), Decimal('0'))
        costs.append(DailyCost(on=on, amount_usd=total * scale))
    return costs


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
def _get(url, *, headers, params):
    try:
        response = requests.get(url, headers=headers, params=params,
                                timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise VendorCostUnavailable(f'Request failed: {exc}') from exc
    except ValueError as exc:
        raise VendorCostUnavailable(f'Response was not JSON: {exc}') from exc


def _get_all_pages(url, *, headers, params):
    """Follow ``has_more`` / ``next_page`` and return every bucket.

    Both providers page their cost reports. Reading only the first page would
    quietly report part of a month's spend as if it were the whole — the same
    class of silent understatement as a stale rate, which is what this module
    exists to eliminate. A partial read is therefore never returned: exhausting
    MAX_PAGES raises instead.
    """
    buckets = []
    page_params = dict(params)

    for _ in range(MAX_PAGES):
        payload = _get(url, headers=headers, params=page_params)
        data = payload.get('data')
        if data is None:
            raise VendorCostUnavailable(
                f'No "data" in cost response (keys: {sorted(payload)})')
        buckets.extend(data)

        if not payload.get('has_more') or not payload.get('next_page'):
            return buckets
        page_params['page'] = payload['next_page']

    raise VendorCostUnavailable(
        f'Cost report still paging after {MAX_PAGES} pages — refusing to '
        f'report a partial total')


def fetch_anthropic_costs(start, end):
    """Daily Anthropic spend, or None when no admin key is configured."""
    key = getattr(settings, 'ANTHROPIC_ADMIN_API_KEY', '')
    if not key:
        logger.info('ANTHROPIC_ADMIN_API_KEY not set — skipping cost fetch')
        return None
    buckets = _get_all_pages(
        ANTHROPIC_COST_URL,
        headers={'x-api-key': key, 'anthropic-version': ANTHROPIC_VERSION},
        params={
            'starting_at': start.isoformat(),
            'ending_at': end.isoformat(),
            'bucket_width': '1d',
        },
    )
    return _extract_daily_costs({'data': buckets},
                                scale=AMOUNT_TO_USD['anthropic'])


def fetch_openai_costs(start, end):
    """Daily OpenAI spend, or None when no admin key is configured."""
    key = getattr(settings, 'OPENAI_ADMIN_API_KEY', '')
    if not key:
        logger.info('OPENAI_ADMIN_API_KEY not set — skipping cost fetch')
        return None
    buckets = _get_all_pages(
        OPENAI_COST_URL,
        headers={'Authorization': f'Bearer {key}'},
        params={
            'start_time': int(datetime(
                start.year, start.month, start.day,
                tzinfo=dt_timezone.utc).timestamp()),
            'end_time': int(datetime(
                end.year, end.month, end.day,
                tzinfo=dt_timezone.utc).timestamp()),
            'bucket_width': '1d',
            'limit': 180,
        },
    )
    return _extract_daily_costs({'data': buckets},
                                scale=AMOUNT_TO_USD['openai'])


# Keyed by AIUsageLog provider value, so the ledger and the invoices agree on
# what a "provider" is.
FETCHERS = {
    'anthropic': fetch_anthropic_costs,
    'openai': fetch_openai_costs,
}
