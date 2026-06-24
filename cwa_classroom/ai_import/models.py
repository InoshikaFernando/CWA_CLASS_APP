from django.conf import settings
from django.db import models


class AIImportUsage(models.Model):
    """Tracks per-school AI import usage per billing period (monthly)."""
    school = models.ForeignKey(
        'classroom.School',
        on_delete=models.CASCADE,
        related_name='ai_import_usage',
    )
    period_start = models.DateField()
    pages_processed = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('school', 'period_start')
        ordering = ['-period_start']

    def __str__(self):
        return f'{self.school.name} — {self.period_start} — {self.pages_processed} pages'


class AIImportSession(models.Model):
    """Temporary storage for AI-classified questions between upload and confirm."""

    # Async processing status — the PDF is classified by a background worker.
    STATUS_PROCESSING = 'processing'
    STATUS_READY = 'ready'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_READY, 'Ready'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_import_sessions',
    )
    school = models.ForeignKey(
        'classroom.School',
        on_delete=models.CASCADE,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pdf_filename = models.CharField(max_length=255)
    # Persisted upload so the background worker (separate process) can read it.
    pdf_file = models.FileField(upload_to='ai_import_pdfs/', null=True, blank=True)
    extracted_data = models.JSONField(default=dict)
    extracted_images = models.JSONField(default=dict)
    page_count = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)
    is_confirmed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_READY,
    )
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.pdf_filename} — {self.user.username} — {"confirmed" if self.is_confirmed else "pending"}'
