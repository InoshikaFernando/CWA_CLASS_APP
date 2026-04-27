from django.db import models
from django.conf import settings
from django.utils import timezone


class Homework(models.Model):
    HOMEWORK_TYPE_CHOICES = [
        ('topic', 'Topic Quiz'),
        ('mixed', 'Mixed Quiz'),
    ]

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.classroom})'

    @property
    def is_past_due(self):
        return timezone.now() > self.due_date

    @property
    def attempts_unlimited(self):
        return self.max_attempts is None


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
