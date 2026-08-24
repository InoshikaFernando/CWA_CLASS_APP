"""Models owned by the progress app.

Historically this app defined none — all progress data lived in the subject
apps and ``progress`` only read from them. :class:`PeriodReport` (CPP-388) is
the exception: an end-of-period report is a *frozen snapshot*, not a live view,
so it has to be stored. Everything else in this app is still read-only over the
subject apps.
"""

from django.conf import settings
from django.db import models


class PeriodReport(models.Model):
    """A student's progress report for one closed week, month or term.

    The report is generated once the period has ended and never recomputed on
    read: ``data`` holds the whole snapshot (see
    ``docs/specs/CPP-388_period_progress_reports.md`` §2), so the PDF a parent
    downloads months later still says exactly what the notification said. Both
    the HTML view and the PDF render from this one dict, which is what stops
    them from disagreeing.
    """

    PERIOD_WEEKLY = 'weekly'
    PERIOD_MONTHLY = 'monthly'
    PERIOD_TERM = 'term'
    PERIOD_CHOICES = [
        (PERIOD_WEEKLY, 'Weekly'),
        (PERIOD_MONTHLY, 'Monthly'),
        (PERIOD_TERM, 'Term'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='period_reports',
    )
    # Null for an individual learner with no school. Term reports need a school
    # (they key off classroom.Term); weekly/monthly ones do not.
    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE,
        null=True, blank=True, related_name='period_reports',
    )
    term = models.ForeignKey(
        'classroom.Term', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='period_reports',
        help_text='Set on term reports; null on weekly/monthly ones.',
    )
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES, db_index=True)
    period_start = models.DateField()
    period_end = models.DateField()

    data = models.JSONField(
        default=dict, blank=True,
        help_text='Frozen snapshot: totals, topics, attempts, trend, awards.',
    )

    generated_at = models.DateTimeField(auto_now_add=True)
    # Delivery state. Null means "not done yet" for both, which is what makes
    # the generator idempotent: a re-run notifies only what it has not already.
    notified_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the in-app notification went to the student and parents.',
    )
    parent_emailed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the end-of-term email went to the parents. Term reports only.',
    )

    class Meta:
        ordering = ['-period_start', 'period_type']
        # One report per student per period. This IS the idempotency key the
        # daily cron relies on — without it a re-run would re-notify.
        unique_together = ('student', 'period_type', 'period_start')
        indexes = [
            models.Index(fields=['student', 'period_type', '-period_start']),
        ]

    def __str__(self):
        return f'{self.student.username} — {self.get_period_type_display()} {self.period_start}'

    # -- Convenience accessors used by the templates and the PDF renderer ----
    # They all tolerate a partially-built ``data`` dict, because a report row
    # is deliberately still created for a student with no activity.

    @property
    def label(self):
        """Human label for the period, e.g. "Week of 17 Aug 2026"."""
        return (self.data.get('period') or {}).get('label') or str(self.period_start)

    @property
    def totals(self):
        return self.data.get('totals') or {}

    @property
    def topics(self):
        return self.data.get('topics') or []

    @property
    def attempts(self):
        return self.data.get('attempts') or {}

    @property
    def trend(self):
        return self.data.get('trend') or []

    @property
    def awards(self):
        return self.data.get('awards') or []

    @property
    def worksheets(self):
        return self.data.get('worksheets') or {}

    @property
    def has_activity(self):
        """True when the student actually submitted something in the window.

        The report row exists either way — an empty period should be visible,
        not hidden — but nothing is notified or celebrated for an empty one.
        """
        return bool(self.totals.get('submissions'))
