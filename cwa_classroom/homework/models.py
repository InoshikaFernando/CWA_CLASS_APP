"""
homework/models.py
==================
Homework, HomeworkSubmission, and HomeworkQuestion models for the Homework
Module (CPP-74).

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

    TYPE_QUIZ = 'quiz'
    TYPE_PDF = 'pdf'
    TYPE_NOTE = 'note'

    TYPE_CHOICES = [
        (TYPE_QUIZ, 'Quiz'),
        (TYPE_PDF, 'PDF Upload'),
        (TYPE_NOTE, 'Note / Message'),
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
        null=True,
        blank=True,
        help_text='Primary topic (used for classification/filtering).',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    homework_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_QUIZ,
    )
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

    # ── PDF type fields ──
    teacher_attachment = models.FileField(
        upload_to='homework/teacher_files/%Y/%m/',
        blank=True,
        null=True,
        help_text="Teacher's worksheet/instructions (PDF type).",
    )

    # ── Quiz type fields ──
    quiz_topics = models.ManyToManyField(
        'classroom.Topic',
        blank=True,
        related_name='quiz_homeworks',
        help_text='Topics/subtopics for quiz-type homework.',
    )
    quiz_level = models.ForeignKey(
        'classroom.Level',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quiz_homeworks',
        help_text='Level for quiz questions.',
    )
    num_questions = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Number of questions to select for quiz homework.',
    )
    min_score_percent = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Minimum score % for quiz homework (informational).',
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

    def snapshot_questions(self):
        """Select and lock in questions for quiz-type homework.

        Randomly picks ``num_questions`` from the selected quiz_topics
        and creates HomeworkQuestion rows with a fixed order.
        """
        if self.homework_type != self.TYPE_QUIZ:
            return

        from maths.models import Question

        topic_ids = list(self.quiz_topics.values_list('id', flat=True))
        if not topic_ids:
            return

        questions = Question.objects.filter(
            topic_id__in=topic_ids,
        )
        if self.quiz_level_id:
            questions = questions.filter(level=self.quiz_level)

        questions = list(questions.order_by('?'))
        if self.num_questions and self.num_questions < len(questions):
            questions = questions[:self.num_questions]

        HomeworkQuestion.objects.filter(homework=self).delete()
        for order, q in enumerate(questions, start=1):
            HomeworkQuestion.objects.create(
                homework=self,
                question=q,
                order=order,
            )


class HomeworkQuestion(models.Model):
    """Snapshot of a question assigned to a quiz-type homework.

    All students receive the same questions in the same order.
    Created when the teacher saves the homework.
    """

    homework = models.ForeignKey(
        Homework,
        on_delete=models.CASCADE,
        related_name='homework_questions',
    )
    question = models.ForeignKey(
        'maths.Question',
        on_delete=models.CASCADE,
        related_name='homework_assignments',
    )
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ['order']
        unique_together = [('homework', 'question')]

    def __str__(self):
        return f'{self.homework.title} — Q{self.order}'


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

    # ── Quiz type fields ──
    quiz_session_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Quiz session UUID for linking back to quiz flow.',
    )
    quiz_result = models.ForeignKey(
        'maths.StudentFinalAnswer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='homework_submissions',
        help_text='Direct link to quiz result for score retrieval.',
    )
    is_auto_completed = models.BooleanField(
        default=False,
        help_text='True when auto-created by quiz completion or mark-as-done.',
    )

    # Grading fields (filled by teacher or auto-graded for quiz)
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
