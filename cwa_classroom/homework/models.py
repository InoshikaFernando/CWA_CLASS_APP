"""
homework/models.py
==================
Homework and HomeworkSubmission models for the Homework Module (CPP-74).

Uses lazy FK strings ('classroom.ClassRoom') to avoid circular imports,
following the attendance app pattern.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Homework(models.Model):
    """A homework assignment created by a teacher for a class."""

    STATUS_DRAFT = 'draft'
    STATUS_SCHEDULED = 'scheduled'
    STATUS_ACTIVE = 'active'
    STATUS_CLOSED = 'closed'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CLOSED, 'Closed'),
    ]

    classroom = models.ForeignKey(
        'classroom.ClassRoom',
        on_delete=models.CASCADE,
        related_name='homeworks',
    )
    topic = models.ForeignKey(
        'classroom.Topic',
        on_delete=models.PROTECT,
        related_name='homeworks',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_homeworks',
    )
    assigned_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField()
    max_attempts = models.PositiveIntegerField(
        default=0,
        help_text='0 = unlimited attempts',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    scheduled_publish_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When to auto-publish (for scheduled status).',
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When this homework was actually published to students.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='False = soft-deleted (hidden from all users).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-due_date']
        indexes = [
            models.Index(fields=['due_date', 'is_active']),
            models.Index(fields=['status', 'scheduled_publish_at']),
        ]

    def __str__(self):
        return f'{self.title} — {self.classroom.name}'

    @property
    def is_overdue(self):
        return (
            self.status == self.STATUS_ACTIVE
            and timezone.now() > self.due_date
        )

    @property
    def is_due_soon(self):
        if self.status != self.STATUS_ACTIVE:
            return False
        now = timezone.now()
        return now < self.due_date <= now + timezone.timedelta(hours=24)

    @property
    def has_submissions(self):
        return self.submissions.exists()

    def can_edit(self):
        return not self.has_submissions and self.status != self.STATUS_CLOSED

    def publish(self):
        self.status = self.STATUS_ACTIVE
        self.published_at = timezone.now()
        self.save(update_fields=['status', 'published_at', 'updated_at'])


class HomeworkSubmission(models.Model):
    """A single submission (attempt) by a student for a homework."""

    homework = models.ForeignKey(
        Homework,
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='homework_submissions',
    )
    attempt_number = models.PositiveIntegerField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_late = models.BooleanField(
        default=False,
        help_text='Computed on save: submitted_at > homework.due_date',
    )
    content = models.TextField(
        blank=True,
        help_text="Student's written answer.",
    )
    attachment = models.FileField(
        upload_to='homework/submissions/%Y/%m/',
        blank=True,
        null=True,
    )

    # Grading fields (filled by teacher)
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    is_graded = models.BooleanField(default=False)
    is_published = models.BooleanField(
        default=False,
        help_text='Controls whether student can see the grade.',
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='graded_submissions',
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-attempt_number']
        unique_together = [('homework', 'student', 'attempt_number')]
        indexes = [
            models.Index(fields=['student', 'homework']),
        ]

    def __str__(self):
        return f'{self.student.username} — {self.homework.title} (attempt {self.attempt_number})'

    def save(self, *args, **kwargs):
        if not self.pk:
            self.is_late = timezone.now() > self.homework.due_date
        super().save(*args, **kwargs)
