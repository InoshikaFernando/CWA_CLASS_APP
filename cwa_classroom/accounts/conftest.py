"""Test fixtures scoped to the accounts app.

Several views (login, registration) are protected by IP-based rate
limiting that lives in Django's cache. Without explicit resets, the
counter accumulates across tests within a single xdist worker — once
a worker has run more than ``max_attempts`` registration tests against
the shared 127.0.0.1 client IP, the next POST returns HTTP 429 and the
test fails. Clearing the cache before each test isolates them from
each other and from any prior counter state.
"""
import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _reset_rate_limit_cache():
    """Clear the rate-limit cache before each accounts test."""
    cache.clear()
    yield
    cache.clear()
