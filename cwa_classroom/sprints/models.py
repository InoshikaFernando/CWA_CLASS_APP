"""Sprint burndown models.

We mirror just enough of a Jira sprint to draw a burndown chart. Jira's REST
API only ever reports an issue's *current* state, so a burndown — "story
points remaining per day" — cannot be reconstructed after the fact. We
therefore record one immutable :class:`SprintSnapshot` per sprint per day from
a scheduled sync, and the chart reads back those rows.
"""
from django.db import models
from django.utils import timezone


class Sprint(models.Model):
    """A single Jira sprint we track a burndown for.

    Keyed on Jira's own numeric sprint id so repeated syncs upsert the same
    row rather than duplicating it.
    """

    STATE_FUTURE = 'future'
    STATE_ACTIVE = 'active'
    STATE_CLOSED = 'closed'
    STATE_CHOICES = [
        (STATE_FUTURE, 'Future'),
        (STATE_ACTIVE, 'Active'),
        (STATE_CLOSED, 'Closed'),
    ]

    jira_sprint_id = models.IntegerField(
        unique=True,
        help_text="Jira's own numeric sprint id (from the Agile API).",
    )
    name = models.CharField(max_length=255)
    state = models.CharField(
        max_length=20, choices=STATE_CHOICES, default=STATE_ACTIVE, db_index=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    goal = models.TextField(blank=True, default='')
    # Story points committed at the start of the sprint. The ideal burndown
    # line runs from this value down to zero across the sprint's days. Captured
    # once (see baseline_captured) so later scope changes don't move it.
    committed_points = models.FloatField(default=0)
    # Set True on the first sync that records a non-zero committed baseline, so
    # the baseline locks instead of re-capturing every run. An explicit flag is
    # used rather than a truthy check on committed_points, since 0 is a valid
    # (not-yet-estimated) baseline.
    baseline_captured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', '-jira_sprint_id']

    def __str__(self):
        return f'{self.name} (#{self.jira_sprint_id})'


class SprintSnapshot(models.Model):
    """Remaining/completed story points for one sprint on one day.

    One row per (sprint, snapshot_date); the daily sync upserts today's row so
    re-running it is idempotent. These rows *are* the burndown series.
    """

    sprint = models.ForeignKey(
        Sprint, on_delete=models.CASCADE, related_name='snapshots',
    )
    snapshot_date = models.DateField(default=timezone.localdate, db_index=True)
    # Sum of story points on issues not yet Done — the burndown's actual line.
    remaining_points = models.FloatField(default=0)
    # Sum of story points on Done issues — handy for tooltips / a burn-up view.
    completed_points = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    # Bumped every time the sync upserts this row. Because a day's snapshot is
    # rewritten in place by each run (3x/day), this — not created_at — is the
    # true "last synced" time the burndown page surfaces.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['snapshot_date']
        constraints = [
            models.UniqueConstraint(
                fields=['sprint', 'snapshot_date'],
                name='unique_sprint_snapshot_per_day',
            ),
        ]

    @property
    def total_points(self):
        """Total scope on this day. Derived (not stored) so the three numbers
        can never disagree; surfaces scope creep against committed_points."""
        return self.remaining_points + self.completed_points

    def __str__(self):
        return f'{self.sprint.name} @ {self.snapshot_date}: {self.remaining_points} left'


class ProjectSnapshot(models.Model):
    """Whole-project story-point burndown — one row per day.

    Unlike :class:`SprintSnapshot` this isn't tied to a sprint: it captures the
    total story points remaining (not-Done) and completed across the *entire*
    Jira project, so the chart shows the project trending toward done over time
    rather than a single sprint. Upserted per day (``snapshot_date`` unique), so
    re-running the sync rewrites today's row.
    """

    snapshot_date = models.DateField(
        default=timezone.localdate, unique=True, db_index=True,
    )
    # Sum of story points on not-Done issues across the project — the line.
    remaining_points = models.FloatField(default=0)
    # Sum of story points on Done issues — total scope = remaining + completed.
    completed_points = models.FloatField(default=0)
    # Count of not-Done issues, for context in the tooltip / a count-based view.
    open_issue_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    # Bumped on every upsert; the page's "last synced" time (see SprintSnapshot).
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['snapshot_date']

    @property
    def total_points(self):
        return self.remaining_points + self.completed_points

    def __str__(self):
        return f'Project @ {self.snapshot_date}: {self.remaining_points} left'
