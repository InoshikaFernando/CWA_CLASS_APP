"""
accounts/signals.py — Audit logging for auth lifecycle events (CPP-271).
"""
import logging
import time

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_out)
def log_logout_event(sender, request, user, **kwargs):
    """Log an audit event when any user logs out."""
    if user is None:
        return

    detail = {}

    # Calculate session duration if login_at was stored
    login_at = None
    if request and hasattr(request, 'session'):
        login_at = request.session.get('login_at')
    if login_at:
        try:
            detail['session_duration_seconds'] = round(time.time() - float(login_at))
        except (ValueError, TypeError):
            pass

    try:
        from audit.services import log_event
        log_event(
            user=user,
            category='auth',
            action='logout',
            detail=detail,
            request=request,
        )
    except Exception:
        logger.exception('Failed to log logout audit event')
