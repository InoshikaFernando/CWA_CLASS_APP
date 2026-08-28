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
    subject = models.ForeignKey(
        'classroom.Subject', on_delete=models.PROTECT,
        null=True, blank=True, related_name='period_reports',
        help_text=(
            'The subject this report covers. Null only on pre-CPP-395 rows that '
            'have not been split yet — here null means "legacy", not "inherit".'
        ),
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
        # One report per student per period PER SUBJECT. This IS the
        # idempotency key the daily cron relies on — without it a re-run would
        # re-notify. Subject joined it in CPP-395 so a student taking maths and
        # coding gets one report about each rather than one about both.
        #
        # MySQL treats NULLs as distinct in a unique index, so a legacy
        # (subject=NULL) row can coexist with the per-subject rows split out of
        # it. That is deliberate: the backfill keeps the original readable.
        unique_together = ('student', 'period_type', 'period_start', 'subject')
        indexes = [
            models.Index(fields=['student', 'period_type', '-period_start']),
        ]

    def __str__(self):
        return f'{self.student.username} — {self.get_period_type_display()} {self.period_start}'

    # -- Convenience accessors used by the templates and the PDF renderer ----
    # They all tolerate a partially-built ``data`` dict, because a report row
    # is deliberately still created for a student with no activity.

    @property
    def sections_included(self):
        """What this report actually carried when it was built.

        Read from the snapshot, never from today's settings: switching a
        section off must not change a report a family has already read. Legacy
        rows predate the key and report everything, which is what they had.
        """
        from progress.models import ProgressReportSetting

        stored = self.data.get('sections_included')
        return stored if stored else dict(ProgressReportSetting.CONTENT_DEFAULTS)

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
    def quizzes(self):
        return self.data.get('quizzes') or {}

    @property
    def times_tables(self):
        return self.data.get('times_tables') or {}

    @property
    def basic_facts(self):
        return self.data.get('basic_facts') or {}

    @property
    def has_activity(self):
        """True when the student actually submitted something in the window.

        The report row exists either way — an empty period should be visible,
        not hidden — but nothing is notified or celebrated for an empty one.
        """
        # Any strand counts, not just homework: a child who spent the week on
        # times tables did work, and a report that called that "no activity"
        # would be telling them it did not count.
        return bool(
            self.totals.get('submissions')
            or self.totals.get('activity_items')
        )


class ProgressReportSetting(models.Model):
    """Which period reports a school, department or class actually sends.

    Reports are **off until switched on**. Generating for every student in
    every school the moment the cron lands would notify thousands of families
    about a feature nobody had seen yet, so there is no "enabled by default"
    here: an unset field inherits, and an unset chain resolves to off.

    Scope is one row per level, most specific wins — the same shape as the fee
    cascade in ``classroom.fee_utils``:

        classroom row → department row → school row → off

    Each flag is ``NULL`` = "inherit from the level above", so a department can
    turn weekly reports on without saying anything about term reports, and a
    single class can opt out of what its department enabled.
    """

    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE,
        related_name='progress_report_settings',
    )
    department = models.ForeignKey(
        'classroom.Department', on_delete=models.CASCADE,
        null=True, blank=True, related_name='progress_report_settings',
        help_text='Set for a department-level rule. Null = school-level.',
    )
    classroom = models.ForeignKey(
        'classroom.ClassRoom', on_delete=models.CASCADE,
        null=True, blank=True, related_name='progress_report_settings',
        help_text='Set for a single class. Null = department/school-level.',
    )

    # Which periods are reported. NULL = inherit.
    weekly = models.BooleanField(null=True, blank=True)
    monthly = models.BooleanField(null=True, blank=True)
    term = models.BooleanField(null=True, blank=True)

    # Who hears about it. NULL = inherit. Separating these from the period
    # flags is what makes a silent trial possible: generate the reports, look
    # at the numbers, and only then turn the notifications on.
    notify_student = models.BooleanField(null=True, blank=True)
    notify_parents = models.BooleanField(null=True, blank=True)
    email_parents_at_term = models.BooleanField(null=True, blank=True)

    # Manual or automatic. NULL = inherit; an unset chain resolves to MANUAL,
    # because a schedule that starts sending on its own is not something a
    # school should acquire by not noticing a setting.
    MODE_MANUAL = 'manual'
    MODE_AUTO = 'auto'
    MODE_CHOICES = [
        (MODE_MANUAL, 'Manual — staff review and send'),
        (MODE_AUTO, 'Automatic — send on the scheduled day'),
    ]
    mode = models.CharField(
        max_length=10, choices=MODE_CHOICES, null=True, blank=True,
        help_text='Null = inherit. An unset chain resolves to manual.',
    )

    # What a report actually contains. NULL = inherit; an unset chain resolves
    # to the CONTENT_DEFAULTS below rather than to off, because a school that
    # switched reporting on wants a report, not an empty page.
    #
    # The two manual sections (rubric, teacher comment) default on but are
    # never REQUIRED: a section with nothing in it is omitted, and nothing here
    # can stop a report generating or sending. See CPP-395 §6.
    include_homework = models.BooleanField(null=True, blank=True)
    include_practice = models.BooleanField(
        null=True, blank=True,
        help_text='Quizzes, times tables and basic facts. Maths reports only — '
                  'a setting cannot make a times table part of a coding report.',
    )
    include_worksheets = models.BooleanField(null=True, blank=True)
    include_topics = models.BooleanField(null=True, blank=True)
    include_awards = models.BooleanField(null=True, blank=True)
    include_rubric = models.BooleanField(null=True, blank=True)
    include_teacher_comment = models.BooleanField(null=True, blank=True)

    # When an automatic run fires. Ignored in manual mode. NULL = inherit.
    send_weekly_on = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Day of week for the weekly run: 0=Monday … 6=Sunday.',
    )
    send_monthly_on = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text=(
            'Day of month for the monthly run (1–28). Capped at 28 so the run '
            'exists in February; a "31st" schedule would skip four months a year.'
        ),
    )
    send_term_after_days = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Days after a term ends before its report is sent.',
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Field name -> whether it defaults to on *once a period is enabled*.
    # The period flags themselves have no such default: off is off.
    PERIOD_FIELDS = ('weekly', 'monthly', 'term')
    DELIVERY_FIELDS = ('notify_student', 'notify_parents', 'email_parents_at_term')
    SCHEDULE_FIELDS = ('send_weekly_on', 'send_monthly_on', 'send_term_after_days')
    CONTENT_FIELDS = (
        'include_homework', 'include_practice', 'include_worksheets',
        'include_topics', 'include_awards', 'include_rubric',
        'include_teacher_comment',
    )
    # Content is opt-OUT once a period is on, unlike the period flags where off
    # is off: a school that asked for reports has asked for their contents.
    CONTENT_DEFAULTS = {field: True for field in CONTENT_FIELDS}

    # Where an automatic run lands when nobody has said otherwise. These match
    # what the periods module already treats as the close of each window:
    # Monday for the week just gone, the 1st for the month, the day after a
    # term ends (so the last day's submissions are inside the window).
    SCHEDULE_DEFAULTS = {
        'send_weekly_on': 0,
        'send_monthly_on': 1,
        'send_term_after_days': 1,
    }
    # The period a schedule field governs.
    SCHEDULE_FOR_PERIOD = {
        'weekly': 'send_weekly_on',
        'monthly': 'send_monthly_on',
        'term': 'send_term_after_days',
    }
    # Delivery defaults apply only to a class that is generating at all, so a
    # school that switches weekly on gets the obvious behaviour without having
    # to tick three more boxes — but can still turn any of them off.
    DELIVERY_DEFAULTS = {
        'notify_student': True,
        'notify_parents': True,
        'email_parents_at_term': True,
    }

    class Meta:
        ordering = ['school', 'department', 'classroom']
        constraints = [
            # One row per scope. Partial constraints because NULL never equals
            # NULL in SQL, so a plain unique_together would let duplicate
            # school-level rows through and make the cascade non-deterministic.
            models.UniqueConstraint(
                fields=['school'],
                condition=models.Q(department__isnull=True, classroom__isnull=True),
                name='unique_progress_setting_school',
            ),
            models.UniqueConstraint(
                fields=['department'],
                condition=models.Q(department__isnull=False, classroom__isnull=True),
                name='unique_progress_setting_department',
            ),
            models.UniqueConstraint(
                fields=['classroom'],
                condition=models.Q(classroom__isnull=False),
                name='unique_progress_setting_classroom',
            ),
        ]

    def __str__(self):
        if self.classroom_id:
            return f'Report settings — {self.classroom}'
        if self.department_id:
            return f'Report settings — {self.department}'
        return f'Report settings — {self.school}'

    @property
    def scope_label(self):
        if self.classroom_id:
            return 'Class'
        if self.department_id:
            return 'Department'
        return 'School'
