from django.conf import settings
from django.db import models
from django.utils import timezone


class Worksheet(models.Model):
    """A PDF worksheet uploaded by a teacher, containing an ordered set of questions."""
    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE, related_name='worksheets',
    )
    name = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    pdf_file = models.FileField(upload_to='worksheets/pdfs/', blank=True, null=True)
    level = models.ForeignKey(
        'classroom.Level', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='worksheets',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_worksheets',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    question_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def refresh_question_count(self):
        self.question_count = self.worksheet_questions.count()
        self.save(update_fields=['question_count'])


class WorksheetQuestion(models.Model):
    """Ordered link between a Worksheet and a question (maths or other subject)."""
    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='worksheet_questions',
    )
    question = models.ForeignKey(
        'maths.Question', on_delete=models.CASCADE, related_name='worksheet_entries',
        null=True, blank=True,
    )
    coding_exercise = models.ForeignKey(
        'coding.CodingExercise', on_delete=models.CASCADE, related_name='worksheet_entries',
        null=True, blank=True,
    )
    order = models.PositiveIntegerField()
    # Subject plugin fields — mirrors HomeworkQuestion pattern.
    # subject_slug + content_id identify the question for any subject plugin.
    # For existing maths questions, content_id == question_id (backfilled by migration).
    subject_slug = models.CharField(
        max_length=50, default='mathematics', db_index=True,
        help_text='Subject plugin slug: mathematics, coding, etc.',
    )
    content_id = models.PositiveIntegerField(
        default=0,
        help_text='pk of the content row (maths.Question.id, CodingExercise.id, etc.).',
    )

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(
                fields=('worksheet', 'order'),
                name='unique_worksheet_question_order',
            ),
            models.UniqueConstraint(
                fields=('worksheet', 'subject_slug', 'content_id'),
                name='unique_worksheet_question_content',
            ),
        ]

    def save(self, *args, **kwargs):
        # Auto-populate content_id from the relevant FK so callers don't have to set it.
        if self.content_id == 0:
            if self.question_id is not None:
                self.content_id = self.question_id
            elif self.coding_exercise_id is not None:
                self.content_id = self.coding_exercise_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.worksheet.name} — Q{self.order}'


class WorksheetUploadSession(models.Model):
    """Temporary storage for AI-extracted worksheet questions between upload and confirm."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='worksheet_upload_sessions',
    )
    school = models.ForeignKey(
        'classroom.School', on_delete=models.CASCADE,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pdf_filename = models.CharField(max_length=255)
    worksheet_name = models.CharField(max_length=255, blank=True)
    extracted_data = models.JSONField(default=dict)
    extracted_images = models.JSONField(default=dict)
    page_count = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)
    is_confirmed = models.BooleanField(default=False)
    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='upload_sessions',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.pdf_filename} — {self.user.username}'


class WorksheetAssignment(models.Model):
    """A teacher assigns a worksheet (or a question subset) to a class."""
    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='assignments',
    )
    classroom = models.ForeignKey(
        'classroom.ClassRoom', on_delete=models.CASCADE, related_name='worksheet_assignments',
    )
    session = models.ForeignKey(
        'classroom.ClassSession', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='worksheet_assignments',
    )
    question_start = models.PositiveIntegerField(
        default=1, help_text='First question order number (1-based)',
    )
    question_end = models.PositiveIntegerField(
        null=True, blank=True, help_text='Last question order number inclusive (null = all)',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_worksheet_assignments',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.worksheet.name} → {self.classroom}'

    @property
    def assigned_questions(self):
        qs = self.worksheet.worksheet_questions.select_related(
            'question__level', 'question__topic',
            'coding_exercise__topic_level__topic__language',
        ).prefetch_related('question__answers').filter(
            order__gte=self.question_start,
        )
        if self.question_end:
            qs = qs.filter(order__lte=self.question_end)
        return qs.order_by('order')

    @property
    def assigned_question_count(self):
        return self.assigned_questions.count()

    def range_display(self):
        total = self.worksheet.question_count
        if not self.question_end or self.question_end >= total:
            if self.question_start == 1:
                return 'All questions'
            return f'Questions {self.question_start} – end'
        return f'Questions {self.question_start} – {self.question_end}'


class WorksheetSubmission(models.Model):
    """A student's session working through a worksheet assignment."""
    assignment = models.ForeignKey(
        WorksheetAssignment, on_delete=models.CASCADE, related_name='submissions',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='worksheet_submissions',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    total_questions = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [('assignment', 'student')]
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.student} — {self.assignment}'

    @property
    def is_complete(self):
        return self.completed_at is not None

    @property
    def percentage(self):
        if not self.total_questions:
            return 0
        return round((self.score / self.total_questions) * 100)

    @property
    def answered_count(self):
        return self.answers.count()


class WorksheetStudentAnswer(models.Model):
    """A student's answer to a single question in a worksheet submission.

    Identified by (submission, subject_slug, content_id) so it works for any
    subject plugin. The ``question`` / ``coding_exercise`` FKs are kept
    nullable for backward-compat and fast joins — content_id is the authoritative key.
    """
    submission = models.ForeignKey(
        WorksheetSubmission, on_delete=models.CASCADE, related_name='answers',
    )
    # Subject-plugin identity — mirrors HomeworkStudentAnswer pattern.
    subject_slug = models.CharField(
        max_length=50, default='mathematics', db_index=True,
    )
    content_id = models.PositiveIntegerField(
        default=0,
        help_text='pk of the content row (maths.Question.id, CodingExercise.id, etc.).',
    )
    # Convenience FKs (nullable — only one will be set per row)
    question = models.ForeignKey(
        'maths.Question', on_delete=models.CASCADE,
        null=True, blank=True, related_name='worksheet_student_answers',
    )
    coding_exercise = models.ForeignKey(
        'coding.CodingExercise', on_delete=models.CASCADE,
        null=True, blank=True, related_name='worksheet_student_answers',
    )
    selected_answer = models.ForeignKey(
        'maths.Answer', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='worksheet_student_answers',
    )
    text_answer = models.TextField(blank=True)
    is_correct = models.BooleanField(default=False)
    points_earned = models.FloatField(default=0.0)
    answered_at = models.DateTimeField(auto_now_add=True)
    # Stores structured answer payloads for non-MCQ question types
    # (e.g. coding: {"code": "...", "stdout": "..."}, long-division steps, etc.)
    answer_data = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [('submission', 'subject_slug', 'content_id')]

    @property
    def ai_score_fraction(self):
        """Compatibility shim — homework result partials read this field directly."""
        return self.answer_data.get('score_fraction')

    @property
    def ai_feedback(self):
        """Compatibility shim — homework result partials read this field directly."""
        return self.answer_data.get('feedback', '')

    def save(self, *args, **kwargs):
        # Auto-populate content_id and subject_slug from FK if not already set.
        if self.content_id == 0:
            if self.question_id:
                self.content_id = self.question_id
                if not self.subject_slug:
                    self.subject_slug = 'mathematics'
            elif self.coding_exercise_id:
                self.content_id = self.coding_exercise_id
                if not self.subject_slug:
                    self.subject_slug = 'coding'
        super().save(*args, **kwargs)

    def __str__(self):
        status = 'Correct' if self.is_correct else 'Wrong'
        return f'{self.submission} — {self.subject_slug}:{self.content_id} — {status}'
