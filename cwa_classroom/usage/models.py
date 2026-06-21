from django.conf import settings
from django.db import models


class PageHit(models.Model):
    """A single tracked page view, recorded by UsageTrackingMiddleware.

    One row per real HTML page load (and per 4xx/5xx response on a page
    route). Powers the superuser Usage Analytics dashboard. Static files,
    /admin/, Stripe webhooks, media and AJAX/HTMX/JSON requests are NOT
    tracked — see usage.middleware for the rules.

    Rows are pruned after ~90 days by the prune_usage_log management command.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=8, default='GET')
    status_code = models.PositiveSmallIntegerField(default=200, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='page_hits',
    )
    # Stored so an anonymous-visitor metric can be added later without a
    # schema change; the dashboard's "distinct users" line uses `user`.
    session_key = models.CharField(max_length=40, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['status_code', 'created_at']),
            models.Index(fields=['path', 'created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.method} {self.path} → {self.status_code}'
