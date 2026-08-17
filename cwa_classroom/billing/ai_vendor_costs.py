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

--------------------------------------------------------------------------
VERIFY THE PARSERS BEFORE TRUSTING THEM
--------------------------------------------------------------------------
The endpoints, auth and parameters below are from the providers' current
documentation. The exact *response shapes* were not verifiable from this
environment, so ``_extract_daily_costs_*`` are written defensively and MUST be
checked against one real response before the figures are believed. They are
deliberately isolated in small functions with fixture-driven tests so that
correcting them is a contained change and cannot silently produce a wrong
total: anything unparseable raises rather than returning 0.
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
def _money(value):
    """Coerce a documented money value to Decimal, or raise.

    Vendors express amounts variously as a float, a string, or an object with
    a value/currency pair. Anything else is refused rather than guessed at.
    """
    if isinstance(value, dict):
        currency = (value.get('currency') or 'usd').lower()
        if currency != 'usd':
            raise VendorCostUnavailable(
                f'Expected USD amounts, got {currency!r}')
        value = value.get('value', value.get('amount'))
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


def _extract_daily_costs(payload):
    """Pull [DailyCost] out of a bucketed cost response.

    Both providers return time buckets each holding cost entries; the entries
    are summed per bucket. Written against that common shape and shared by both
    adapters — if they diverge, split this rather than adding special cases,
    so each remains obvious.
    """
    buckets = payload.get('data')
    if buckets is None:
        raise VendorCostUnavailable(
            f'No "data" in cost response (keys: {sorted(payload)})')

    costs = []
    for bucket in buckets:
        on = _bucket_date(bucket)
        entries = bucket.get('results', bucket.get('items', []))
        total = sum((_money(e.get('amount', e)) for e in entries), Decimal('0'))
        costs.append(DailyCost(on=on, amount_usd=total))
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


def fetch_anthropic_costs(start, end):
    """Daily Anthropic spend, or None when no admin key is configured."""
    key = getattr(settings, 'ANTHROPIC_ADMIN_API_KEY', '')
    if not key:
        logger.info('ANTHROPIC_ADMIN_API_KEY not set — skipping cost fetch')
        return None
    payload = _get(
        ANTHROPIC_COST_URL,
        headers={'x-api-key': key, 'anthropic-version': ANTHROPIC_VERSION},
        params={
            'starting_at': start.isoformat(),
            'ending_at': end.isoformat(),
            'bucket_width': '1d',
        },
    )
    return _extract_daily_costs(payload)


def fetch_openai_costs(start, end):
    """Daily OpenAI spend, or None when no admin key is configured."""
    key = getattr(settings, 'OPENAI_ADMIN_API_KEY', '')
    if not key:
        logger.info('OPENAI_ADMIN_API_KEY not set — skipping cost fetch')
        return None
    payload = _get(
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
    return _extract_daily_costs(payload)


# Keyed by AIUsageLog provider value, so the ledger and the invoices agree on
# what a "provider" is.
FETCHERS = {
    'anthropic': fetch_anthropic_costs,
    'openai': fetch_openai_costs,
}
