"""
Audit logging service.

Usage:
    from audit.services import log_event

    # In a view with request context:
    log_event(
        user=request.user,
        school=school,
        category='auth',
        action='login_success',
        request=request,
    )

    # With extra detail:
    log_event(
        user=user,
        category='entitlement',
        action='class_limit_exceeded',
        result='blocked',
        detail={'current': 5, 'limit': 5, 'plan': 'Basic'},
        request=request,
    )
"""
import logging

from .models import AuditLog

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Extract client IP from request, handling proxies."""
    if not request:
        return None
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_event(
    user=None,
    school=None,
    category='',
    action='',
    result='allowed',
    detail=None,
    request=None,
):
    """
    Create an audit log entry.

    Args:
        user: The user performing the action (or target user).
        school: The school context (if applicable).
        category: One of: auth, billing, entitlement, admin_action, data_change.
        action: Specific action string (e.g., 'login_success', 'class_limit_exceeded').
        result: 'allowed' or 'blocked'.
        detail: Dict of additional context.
        request: Django HttpRequest for IP/UA extraction.
    """
    try:
        ip = get_client_ip(request) if request else None
        ua = ''
        endpoint = ''
        if request:
            ua = request.META.get('HTTP_USER_AGENT', '')[:500]
            endpoint = request.path[:255]

        # Handle anonymous or non-saved users
        user_to_save = user if (user and hasattr(user, 'pk') and user.pk) else None
        school_to_save = school if (school and hasattr(school, 'pk') and school.pk) else None

        AuditLog.objects.create(
            user=user_to_save,
            school=school_to_save,
            category=category,
            action=action,
            result=result,
            detail=detail or {},
            ip_address=ip,
            user_agent=ua,
            endpoint=endpoint,
        )
    except Exception:
        # Never let audit logging break the application
        logger.exception('Failed to create audit log: action=%s', action)
