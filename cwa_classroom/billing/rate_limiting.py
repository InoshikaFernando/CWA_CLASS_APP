"""
Rate limiting utility using Django's cache framework.

Usage:
    from billing.rate_limiting import check_rate_limit

    # In a view:
    if not check_rate_limit(f'login:{ip}', max_attempts=5, window_seconds=900):
        return HttpResponse('Too many attempts', status=429)
"""
from django.core.cache import cache


def check_rate_limit(key, max_attempts, window_seconds):
    """
    Check if an action is within its rate limit.

    Args:
        key: Unique identifier (e.g., 'login:192.168.1.1')
        max_attempts: Maximum allowed attempts in the window
        window_seconds: Time window in seconds

    Returns:
        True if within limit (action allowed), False if rate limited.
    """
    cache_key = f'ratelimit:{key}'
    count = cache.get(cache_key, 0)
    if count >= max_attempts:
        return False
    cache.set(cache_key, count + 1, window_seconds)
    return True


def get_remaining_attempts(key, max_attempts):
    """Get the number of remaining attempts for a rate-limited action."""
    cache_key = f'ratelimit:{key}'
    count = cache.get(cache_key, 0)
    return max(0, max_attempts - count)


def reset_rate_limit(key):
    """Clear the rate limit counter for a key (e.g., after successful login)."""
    cache.delete(f'ratelimit:{key}')
