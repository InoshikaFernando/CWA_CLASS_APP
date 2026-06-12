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
