from django.db import models
from django.conf import settings
from django.utils import timezone


class HomeworkUploadSession(models.Model):
    """Temporary staging record between PDF upload steps (upload → preview → confirm)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='homework_upload_sessions',
    )
    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE, null=True, blank=True,
    )
    classroom = models.ForeignKey(
        'classroom.ClassRoom', on_delete=models.SET_NULL, null=True, blank=True,
        help_text='Pre-selected classroom target, set at upload time.',
    )
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_ERROR, 'Error'),
    ]

    pdf_filename = models.CharField(max_length=255)
    pdf_file = models.FileField(
        upload_to='homework_uploads/', null=True, blank=True,
        help_text='Stored temporarily while AI extraction runs in the background.',
    )
    homework_title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PROCESSING)
    error_message = models.TextField(blank=True)
    extracted_data = models.JSONField(default=dict)
    extracted_images = models.JSONField(default=dict)
    page_count = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)
    is_confirmed = models.BooleanField(default=False)
    homework = models.ForeignKey(
        'Homework', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='upload_sessions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.pdf_filename} — {self.user.username} — {"confirmed" if self.is_confirmed else "pending"}'


class Homework(models.Model):
    HOMEWORK_TYPE_CHOICES = [
        ('topic', 'Topic Quiz'),
        ('mixed', 'Mixed Quiz'),
        ('pdf_upload', 'PDF Upload'),
    ]

    # Lifecycle status (derived from publish_at / published_at / due_date).
    STATUS_CREATED = 'created'      # saved but not yet live — hidden from students
    STATUS_PUBLISHED = 'published'  # live and visible to students
    STATUS_EXPIRED = 'expired'      # due date has passed

    classroom = models.ForeignKey(
        'classroom.ClassRoom', on_delete=models.CASCADE, related_name='homework_assignments'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_homework'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    homework_type = models.CharField(max_length=20, choices=HOMEWORK_TYPE_CHOICES, default='topic')
    subject_slug = models.CharField(
        max_length=50, default='mathematics', db_index=True,
        help_text=(
            'Which subject-plugin owns this homework — drives topic picker, '
            'item rendering and grading via classroom.subject_registry.'
        ),
    )
    topics = models.ManyToManyField('classroom.Topic', related_name='homework_assignments', blank=True)
    # Phase 2b: coding homework uses coding.CodingTopic, not classroom.Topic.
    coding_topics = models.ManyToManyField(
        'coding.CodingTopic', related_name='homework_assignments', blank=True,
    )
    num_questions = models.PositiveIntegerField(default=10)
    due_date = models.DateTimeField()
    max_attempts = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Leave blank for unlimited attempts.',
    )
    publish_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'When this homework should automatically go live. Leave blank to '
            'publish immediately on creation. A future value schedules it — '
            'students see nothing and get no email until then.'
        ),
    )
    published_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'Set when the homework actually went live. This is the single gate '
            'for student visibility and the publish notification email.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.classroom})'

    def save(self, *args, **kwargs):
        # Default to "published immediately on creation" unless a publish time
        # was scheduled. This preserves the pre-scheduling behaviour (homework
        # was always live the moment it was created) so existing callers and
        # the published_at visibility gate keep working; scheduling for later
        # is opt-in by setting ``publish_at``.
        if self.pk is None and self.published_at is None and self.publish_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_past_due(self):
        return timezone.now() > self.due_date

    def is_overdue_for(self, joined_at):
        """Whether this homework is *overdue* for a specific student.

        Overdue is relative to the student, not just the clock: it only
        applies when the homework is past due AND the student was already
        enrolled on or before the due date. A student who joined the class
        after the due date never sees it as overdue — for them it is just a
        normal (still attemptable) assignment.
        """
        if not self.is_past_due:
            return False
        return joined_at is None or joined_at <= self.due_date

    @property
    def attempts_unlimited(self):
        return self.max_attempts is None

    @property
    def is_published(self):
        return self.published_at is not None

    @property
    def status(self):
        """Lifecycle status for display.

        The due date is the hard end of life, so an expired homework reports
        ``expired`` regardless of whether it was ever published. Otherwise it
        is ``published`` once it has gone live, else ``created`` (saved but not
        yet visible to students — covers both drafts and scheduled-for-later).
        """
        if self.due_date and timezone.now() >= self.due_date:
            return self.STATUS_EXPIRED
        return self.STATUS_PUBLISHED if self.is_published else self.STATUS_CREATED

    @property
    def status_label(self):
        return {
            self.STATUS_CREATED: 'Created',
            self.STATUS_PUBLISHED: 'Published',
            self.STATUS_EXPIRED: 'Expired',
        }[self.status]

    def publish(self):
        """Mark the homework live now and notify students.

        Idempotent: a homework that is already published is left untouched so
        the scheduled-publish cron and a manual "Publish now" click can never
        double-send the notification email.
        """
        if self.published_at:
            return
        self.published_at = timezone.now()
        self.save(update_fields=['published_at', 'updated_at'])
        from .services import notify_students_homework_published
        notify_students_homework_published(self)


class HomeworkQuestion(models.Model):
    """The fixed set of items assigned to a homework. Same for all students.

    Phase 2 of the subject-plugin refactor: rows are identified by
    ``(subject_slug, content_id)`` so a homework can hold items from any
    subject (maths ``Question``, coding ``CodingExercise``, etc.). The legacy
    ``question`` FK is kept nullable so existing maths rows still join cleanly
    and admin tooling keeps working during the transition.
    """
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='homework_questions')
    # Legacy maths-only FK. Nullable post-Phase-2; for non-maths subjects this
    # stays None and ``content_id`` carries the pk instead.
    question = models.ForeignKey(
        'maths.Question', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='homework_question_entries',
    )
    subject_slug = models.CharField(
        max_length=50, default='mathematics', db_index=True,
        help_text='Binds to classroom.subject_registry plugin slug.',
    )
    content_id = models.PositiveIntegerField(
        default=0,
        help_text='pk of the underlying content row (maths.Question.id, coding.CodingExercise.id, ...).',
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = ('homework', 'subject_slug', 'content_id')

    def save(self, *args, **kwargs):
        # Back-compat: legacy callers that only set ``question=...`` (e.g.
        # older test fixtures) get ``subject_slug`` + ``content_id`` derived
        # from the maths FK automatically — otherwise the new unique
        # constraint ``(homework, subject_slug, content_id)`` would reject
        # bulk creates that all share content_id=0.
        if self.question_id and (not self.content_id or self.content_id == 0):
            self.content_id = self.question_id
            if not self.subject_slug:
                self.subject_slug = 'mathematics'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.homework} — Q{self.order}'


class HomeworkSubmission(models.Model):
    STATUS_ON_TIME = 'on_time'
    STATUS_LATE = 'late'
    STATUS_NOT_SUBMITTED = 'not_submitted'

    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='homework_submissions'
    )
    attempt_number = models.PositiveIntegerField(default=1)
    score = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=0)
    points = models.FloatField(default=0.0)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        unique_together = ('homework', 'student', 'attempt_number')

    def __str__(self):
        return f'{self.student} — {self.homework} attempt {self.attempt_number}'

    @property
    def submission_status(self):
        if self.submitted_at <= self.homework.due_date:
            return self.STATUS_ON_TIME
        return self.STATUS_LATE

    def submission_status_for(self, joined_at):
        """Submission status relative to a student's join date.

        A student who joined the class after the due date can never submit
        "late" — the deadline passed before they were a member — so their
        submission is always reported as on time. Otherwise this falls back
        to the plain ``submission_status`` comparison.
        """
        if joined_at is not None and joined_at > self.homework.due_date:
            return self.STATUS_ON_TIME
        return self.submission_status

    @property
    def percentage(self):
        if not self.total_questions:
            return 0
        return round((self.score / self.total_questions) * 100)

    @classmethod
    def get_attempt_count(cls, homework, student):
        return cls.objects.filter(homework=homework, student=student).count()

    @classmethod
    def get_best_submission(cls, homework, student):
        return cls.objects.filter(homework=homework, student=student).order_by('-points').first()

    @classmethod
    def get_next_attempt_number(cls, homework, student):
        from django.db.models import Max
        result = cls.objects.filter(homework=homework, student=student).aggregate(max_att=Max('attempt_number'))
        return (result['max_att'] or 0) + 1


class HomeworkStudentAnswer(models.Model):
    """A student's answer to one item in a homework submission.

    Phase 2 of the subject-plugin refactor: rows are identified by
    ``(subject_slug, content_id)``. ``answer_data`` is a plugin-specific blob
    (e.g. the code the student submitted for a coding exercise). Legacy
    ``question`` / ``selected_answer`` / ``text_answer`` fields stay nullable
    for backward compat with existing maths rows and admin tooling.
    """

    # Review status for extended / AI / human-graded answers
    REVIEW_AUTO = 'auto_graded'
    REVIEW_PENDING_AI = 'pending_ai'
    REVIEW_AI_DONE = 'ai_graded'
    REVIEW_PENDING_TEACHER = 'pending_teacher'
    REVIEW_TEACHER_DONE = 'teacher_graded'

    REVIEW_STATUS_CHOICES = [
        (REVIEW_AUTO, 'Auto Graded'),
        (REVIEW_PENDING_AI, 'Pending AI Review'),
        (REVIEW_AI_DONE, 'AI Graded'),
        (REVIEW_PENDING_TEACHER, 'Pending Teacher Review'),
        (REVIEW_TEACHER_DONE, 'Teacher Graded'),
    ]

    submission = models.ForeignKey(HomeworkSubmission, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(
        'maths.Question', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='homework_student_answers',
    )
    selected_answer = models.ForeignKey(
        'maths.Answer', on_delete=models.SET_NULL, null=True, blank=True,
    )
    subject_slug = models.CharField(
        max_length=50, default='mathematics', db_index=True,
        help_text='Binds to classroom.subject_registry plugin slug.',
    )
    content_id = models.PositiveIntegerField(
        default=0,
        help_text='pk of the underlying content row (maths.Question.id, coding.CodingExercise.id, ...).',
    )
    answer_data = models.JSONField(
        default=dict, blank=True,
        help_text='Plugin-specific answer payload (e.g. submitted code, run output).',
    )
    text_answer = models.TextField(blank=True)
    is_correct = models.BooleanField(default=False)
    points_earned = models.FloatField(default=0.0)

    # Grading review fields
    review_status = models.CharField(
        max_length=20, choices=REVIEW_STATUS_CHOICES, default=REVIEW_AUTO,
    )
    ai_feedback = models.TextField(
        blank=True,
        help_text='Feedback generated by Claude when grading this answer.',
    )
    ai_score_fraction = models.FloatField(
        null=True, blank=True,
        help_text='Claude confidence score 0.0–1.0. Multiplied by question points.',
    )
    teacher_feedback = models.TextField(
        blank=True,
        help_text='Feedback written by the teacher when manually grading.',
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='graded_homework_answers',
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('submission', 'subject_slug', 'content_id')

    def save(self, *args, **kwargs):
        # Back-compat: same treatment as HomeworkQuestion.save — legacy
        # direct-create callers (tests, signals, admin) get the new fields
        # inferred from the maths FK so the new unique constraint is satisfied.
        if self.question_id and (not self.content_id or self.content_id == 0):
            self.content_id = self.question_id
            if not self.subject_slug:
                self.subject_slug = 'mathematics'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.submission} — {self.subject_slug}:{self.content_id} — {"Correct" if self.is_correct else "Wrong"}'

    @property
    def is_pending_review(self):
        return self.review_status in (self.REVIEW_PENDING_AI, self.REVIEW_PENDING_TEACHER)

    @property
    def feedback_for_student(self):
        """Return the best available feedback to show the student."""
        if self.review_status == self.REVIEW_TEACHER_DONE:
            return self.teacher_feedback or self.ai_feedback
        if self.review_status == self.REVIEW_AI_DONE:
            return self.ai_feedback
        if self.question:
            return self.question.explanation
        return ''


class AIGradingCache(models.Model):
    """
    Caches AI grading results for extended-answer questions.

    When a new student submits an answer, we first normalise + fuzzy-match
    against this table (Levenshtein ratio > 0.85).  Cache hits cost 0 tokens
    and return instantly.  Only genuinely novel answer patterns call the API.

    Expected savings: ~80% for a class set (5-8 unique patterns, 22-25 hits).
    """
    question = models.ForeignKey(
        'maths.Question', on_delete=models.CASCADE,
        related_name='grading_cache_entries',
    )
    normalised_answer = models.CharField(
        max_length=500,
        help_text='Lowercased, whitespace-collapsed answer text (first 500 chars) used for matching.',
    )
    is_correct = models.BooleanField()
    score_fraction = models.FloatField(
        help_text='Claude score 0.0–1.0.',
    )
    feedback = models.TextField(
        help_text='Feedback returned by Claude for this answer pattern.',
    )
    hit_count = models.PositiveIntegerField(
        default=0,
        help_text='How many subsequent student answers matched this cache entry.',
    )
    human_verified = models.BooleanField(
        default=False,
        help_text='True when a teacher manually graded this answer — used as a golden example.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One cache entry per (question, exact-normalised-answer).
        # Fuzzy matches reuse existing entries without creating duplicates.
        unique_together = ('question', 'normalised_answer')
        ordering = ['-hit_count', '-created_at']
        indexes = [
            models.Index(fields=['question'], name='grading_cache_question_idx'),
        ]

    def __str__(self):
        return f'Cache Q{self.question_id} — score={self.score_fraction:.2f} hits={self.hit_count}'
