from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Records critical system events for security monitoring and compliance.

    Events logged: login attempts, feature access denials, payment events,
    plan limit violations, admin actions, account blocks.
    """

    CATEGORY_AUTH = 'auth'
    CATEGORY_BILLING = 'billing'
    CATEGORY_ENTITLEMENT = 'entitlement'
    CATEGORY_ADMIN_ACTION = 'admin_action'
    CATEGORY_DATA_CHANGE = 'data_change'

    CATEGORY_CHOICES = [
        (CATEGORY_AUTH, 'Authentication'),
        (CATEGORY_BILLING, 'Billing'),
        (CATEGORY_ENTITLEMENT, 'Entitlement'),
        (CATEGORY_ADMIN_ACTION, 'Admin Action'),
        (CATEGORY_DATA_CHANGE, 'Data Change'),
    ]

    RESULT_ALLOWED = 'allowed'
    RESULT_BLOCKED = 'blocked'
    RESULT_CHOICES = [
        (RESULT_ALLOWED, 'Allowed'),
        (RESULT_BLOCKED, 'Blocked'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    school = models.ForeignKey(
        'classroom.School',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    action = models.CharField(max_length=100, db_index=True)
    result = models.CharField(
        max_length=10, choices=RESULT_CHOICES,
        default=RESULT_ALLOWED,
    )
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    endpoint = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'category']),
            models.Index(fields=['school', 'category']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['category', 'result', 'created_at']),
        ]

    def __str__(self):
        user_str = self.user.username if self.user else 'anonymous'
        return f'{self.action} — {user_str} — {self.result}'
