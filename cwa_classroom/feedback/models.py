from django.conf import settings
from django.db import models
from django.utils import timezone


class FeedbackQuerySet(models.QuerySet):
    def active(self):
        """Exclude soft-deleted feedback (removed_at set)."""
        return self.filter(removed_at__isnull=True)

    def removed(self):
        return self.filter(removed_at__isnull=False)


class Feedback(models.Model):
    """
    A single piece of user feedback — a bug report, feature request or
    improvement suggestion — submitted by any authenticated user from
    anywhere in the app (CPP-321 / CPP-322).

    Feedback is platform-wide: it is captured against the submitter's school
    (tenant context) for reporting, but is triaged centrally by the product
    owner rather than per-school (CPP-323).
    """

    # ── Category ────────────────────────────────────────────────────────
    CATEGORY_BUG = 'bug'
    CATEGORY_FEATURE = 'feature'
    CATEGORY_IMPROVEMENT = 'improvement'
    CATEGORY_CHOICES = [
        (CATEGORY_BUG, 'Bug'),
        (CATEGORY_FEATURE, 'Feature request'),
        (CATEGORY_IMPROVEMENT, 'Improvement'),
    ]

    # ── Status lifecycle (shared by capture + triage) ───────────────────
    STATUS_NEW = 'new'
    STATUS_TRIAGED = 'triaged'
    STATUS_PLANNED = 'planned'
    STATUS_DONE = 'done'
    STATUS_REJECTED = 'rejected'
    STATUS_DUPLICATE = 'duplicate'
    STATUS_CHOICES = [
        (STATUS_NEW, 'New'),
        (STATUS_TRIAGED, 'Triaged'),
        (STATUS_PLANNED, 'Planned'),
        (STATUS_DONE, 'Done'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_DUPLICATE, 'Duplicate'),
    ]

    # ── Priority (set during triage) ────────────────────────────────────
    PRIORITY_LOW = 'low'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_HIGH = 'high'
    PRIORITY_CRITICAL = 'critical'
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
        (PRIORITY_CRITICAL, 'Critical'),
    ]

    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE,
        null=True, blank=True, db_index=True,
        related_name='feedback_items',
        help_text="Submitter's school (tenant context). Null for users not "
                  'attached to a school, e.g. individual students.',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='submitted_feedback',
    )
    role = models.CharField(
        max_length=50, blank=True,
        help_text="Submitter's primary role at submission time.",
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField()
    page_url = models.CharField(
        max_length=500, blank=True,
        help_text='URL of the page the feedback was raised from.',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True,
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, blank=True, null=True,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_feedback',
        help_text='Product owner the item is assigned to for triage.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    removed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Soft-delete timestamp. Set to hide the item from queues.',
    )

    objects = FeedbackQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'feedback'
        verbose_name_plural = 'feedback'

    def __str__(self):
        return f'{self.get_category_display()}: {self.title or self.description[:40]}'

    def soft_delete(self):
        """Mark the item as removed without deleting the row."""
        self.removed_at = timezone.now()
        self.save(update_fields=['removed_at', 'updated_at'])

    @property
    def is_removed(self):
        return self.removed_at is not None
