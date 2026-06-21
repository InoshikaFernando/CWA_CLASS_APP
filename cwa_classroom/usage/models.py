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
    # Legacy anonymous identifier — often empty (Django only assigns a
    # session_key once the session is saved). Kept for back-compat; the guest
    # metric now uses `client_key` instead.
    session_key = models.CharField(max_length=40, blank=True)
    # Salted hash of client IP + user agent, set on every hit. Lets the
    # "guests active now" metric count distinct anonymous visitors reliably
    # (unlike session_key, which is blank for visitors who never save a
    # session). Not reversible to an IP.
    client_key = models.CharField(max_length=32, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['status_code', 'created_at']),
            models.Index(fields=['path', 'created_at']),
            # Covering index for the active-users series' window fetch
            # (SELECT created_at, user WHERE created_at >= ...): lets it scan
            # index-only instead of hitting the table.
            models.Index(fields=['created_at', 'user']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.method} {self.path} → {self.status_code}'
