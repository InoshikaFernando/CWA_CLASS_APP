from django.conf import settings
from django.db import models


class BackgroundTask(models.Model):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (RUNNING, 'Running'),
        (DONE, 'Done'),
        (FAILED, 'Failed'),
    ]

    MAX_RETRIES = 3

    school = models.ForeignKey(
        'classroom.School',
        on_delete=models.CASCADE,
        related_name='background_tasks',
        db_index=True,
        null=True, blank=True,
    )
    task_type = models.CharField(max_length=50, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING,
        db_index=True,
    )
    rq_job_id = models.CharField(max_length=255, unique=True)
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='background_tasks',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.task_type} ({self.status}) — {self.school}'


class AIUsageLog(models.Model):
    """One row per AI classification run — the cost/usage ledger.

    Records pages processed, input/output tokens and the estimated USD cost of
    each Claude classification, tagged by which feature triggered it. Lets us
    compute real $/page and margin per source instead of guessing.
    """
    SOURCE_WORKSHEET = 'worksheet'
    SOURCE_AI_IMPORT = 'ai_import'
    SOURCE_HOMEWORK = 'homework'
    SOURCE_CHOICES = [
        (SOURCE_WORKSHEET, 'Worksheet'),
        (SOURCE_AI_IMPORT, 'AI Import'),
        (SOURCE_HOMEWORK, 'Homework PDF'),
    ]

    school = models.ForeignKey(
        'classroom.School',
        on_delete=models.SET_NULL,
        related_name='ai_usage_logs',
        null=True, blank=True,
        db_index=True,
    )
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, db_index=True,
    )
    session_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='PK of the upload session that produced this usage.',
    )
    pages = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    est_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=5, default=0,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source} — {self.pages}p — ${self.est_cost_usd}'

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    @property
    def cost_per_page_usd(self):
        if not self.pages:
            return None
        return self.est_cost_usd / self.pages
