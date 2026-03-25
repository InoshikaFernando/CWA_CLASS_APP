"""
Risk detection functions that query AuditLog for suspicious patterns.

These can be called from management commands, backoffice views,
or scheduled tasks to flag accounts for review.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .models import AuditLog


def detect_trial_abuse(days=30, ip_threshold=3):
    """
    Find IP addresses that have registered multiple accounts recently.
    Returns a list of dicts with IP, registration count, and usernames.
    """
    cutoff = timezone.now() - timedelta(days=days)
    results = (
        AuditLog.objects.filter(
            action='login_success',
            created_at__gte=cutoff,
            ip_address__isnull=False,
        )
        .values('ip_address')
        .annotate(
            user_count=Count('user', distinct=True),
        )
        .filter(user_count__gte=ip_threshold)
        .order_by('-user_count')
    )

    flagged = []
    for row in results:
        ip = row['ip_address']
        usernames = list(
            AuditLog.objects.filter(
                action='login_success',
                ip_address=ip,
                created_at__gte=cutoff,
            )
            .values_list('user__username', flat=True)
            .distinct()[:10]
        )
        flagged.append({
            'ip_address': ip,
            'user_count': row['user_count'],
            'usernames': usernames,
            'risk_level': 'high' if row['user_count'] >= 5 else 'medium',
        })
    return flagged


def detect_rapid_login_failures(threshold=5, window_minutes=15):
    """
    Find users or IPs with many failed login attempts in a short window.
    Returns list of dicts with IP/username and failure counts.
    """
    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    results = (
        AuditLog.objects.filter(
            action='login_failed',
            created_at__gte=cutoff,
        )
        .values('ip_address')
        .annotate(failure_count=Count('id'))
        .filter(failure_count__gte=threshold)
        .order_by('-failure_count')
    )

    flagged = []
    for row in results:
        flagged.append({
            'ip_address': row['ip_address'],
            'failure_count': row['failure_count'],
            'window_minutes': window_minutes,
            'risk_level': 'critical' if row['failure_count'] >= 10 else 'high',
        })
    return flagged


def detect_payment_failure_pattern(threshold=3, days=30):
    """
    Find subscriptions with repeated payment failures.
    Returns list of flagged entries from the audit log.
    """
    cutoff = timezone.now() - timedelta(days=days)
    results = (
        AuditLog.objects.filter(
            action='payment_failed',
            created_at__gte=cutoff,
        )
        .values('detail__stripe_subscription_id')
        .annotate(failure_count=Count('id'))
        .filter(failure_count__gte=threshold)
        .order_by('-failure_count')
    )

    flagged = []
    for row in results:
        flagged.append({
            'stripe_subscription_id': row['detail__stripe_subscription_id'],
            'failure_count': row['failure_count'],
            'risk_level': 'high' if row['failure_count'] >= 5 else 'medium',
        })
    return flagged


def detect_module_abuse(threshold=20, window_minutes=60):
    """
    Find users who are repeatedly hitting gated features (possible bypass attempts).
    """
    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    results = (
        AuditLog.objects.filter(
            action='module_access_denied',
            created_at__gte=cutoff,
        )
        .values('user__username', 'user_id')
        .annotate(attempt_count=Count('id'))
        .filter(attempt_count__gte=threshold)
        .order_by('-attempt_count')
    )

    flagged = []
    for row in results:
        flagged.append({
            'username': row['user__username'],
            'user_id': row['user_id'],
            'attempt_count': row['attempt_count'],
            'risk_level': 'medium',
        })
    return flagged


def get_risk_summary():
    """
    Get an overall risk summary for the backoffice dashboard.
    Returns counts by risk category.
    """
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    return {
        'login_failures_24h': AuditLog.objects.filter(
            action='login_failed', created_at__gte=last_24h,
        ).count(),
        'rate_limited_24h': AuditLog.objects.filter(
            action='login_rate_limited', created_at__gte=last_24h,
        ).count(),
        'module_denials_7d': AuditLog.objects.filter(
            action='module_access_denied', created_at__gte=last_7d,
        ).count(),
        'payment_failures_7d': AuditLog.objects.filter(
            action='payment_failed', created_at__gte=last_7d,
        ).count(),
        'blocked_access_7d': AuditLog.objects.filter(
            action__in=['blocked_user_access_attempt', 'suspended_school_access_attempt'],
            created_at__gte=last_7d,
        ).count(),
        'subscription_expired_7d': AuditLog.objects.filter(
            action='subscription_expired_access', created_at__gte=last_7d,
        ).count(),
    }
