import uuid
from django.db import models
from django.conf import settings


class StudentAnswer(models.Model):
    """Individual student response to a single question."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_answers',
    )
    question = models.ForeignKey(
        'quiz.Question',
        on_delete=models.CASCADE,
        related_name='student_answers',
    )
    topic = models.ForeignKey(
        'classroom.Topic',
        on_delete=models.SET_NULL,
        null=True,
        related_name='student_answers',
        help_text='Stored explicitly to enable per-topic breakdown in Mixed Quiz.',
    )
    level = models.ForeignKey(
        'classroom.Level',
        on_delete=models.SET_NULL,
        null=True,
        related_name='student_answers',
    )
    # The answer the student gave
    selected_answer = models.ForeignKey(
        'quiz.Answer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='selected_by',
    )
    text_answer = models.TextField(blank=True)
    ordered_answer_ids = models.JSONField(null=True, blank=True)  # For drag_drop

    is_correct = models.BooleanField(default=False)
    attempt_id = models.UUIDField(default=uuid.uuid4)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-answered_at']
        indexes = [
            models.Index(fields=['student', 'topic', 'level']),
            models.Index(fields=['attempt_id']),
        ]

    def __str__(self):
        return f'{self.student.username} — Q{self.question_id} — {"✓" if self.is_correct else "✗"}'


class StudentFinalAnswer(models.Model):
    """Aggregated result per quiz attempt (session)."""
    QUIZ_TYPE_TOPIC = 'topic'
    QUIZ_TYPE_MIXED = 'mixed'
    QUIZ_TYPE_TIMES_TABLE = 'times_table'

    QUIZ_TYPE_CHOICES = [
        (QUIZ_TYPE_TOPIC, 'Topic Quiz'),
        (QUIZ_TYPE_MIXED, 'Mixed Quiz'),
        (QUIZ_TYPE_TIMES_TABLE, 'Times Table'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='final_answers',
    )
    topic = models.ForeignKey(
        'classroom.Topic',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='final_answers',
    )
    level = models.ForeignKey(
        'classroom.Level',
        on_delete=models.SET_NULL,
        null=True,
        related_name='final_answers',
    )
    quiz_type = models.CharField(max_length=20, choices=QUIZ_TYPE_CHOICES, default=QUIZ_TYPE_TOPIC)
    session_id = models.UUIDField(default=uuid.uuid4, unique=True)
    attempt_number = models.PositiveIntegerField(default=1)
    score = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=0)
    points = models.FloatField(default=0.0)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']
        indexes = [
            models.Index(fields=['student', 'topic', 'level']),
            models.Index(fields=['session_id']),
        ]

    def __str__(self):
        return f'{self.student.username} — {self.topic} L{self.level_id} — {self.points:.1f}pts'

    @property
    def percentage(self):
        if self.total_questions == 0:
            return 0
        return round((self.score / self.total_questions) * 100)

    @classmethod
    def get_best_result(cls, student, topic, level):
        return cls.objects.filter(
            student=student, topic=topic, level=level
        ).order_by('-points').first()

    @classmethod
    def get_latest_attempt(cls, student, topic, level):
        return cls.objects.filter(
            student=student, topic=topic, level=level
        ).order_by('-completed_at').first()

    @classmethod
    def get_next_attempt_number(cls, student, topic, level):
        last = cls.objects.filter(
            student=student, topic=topic, level=level
        ).order_by('-attempt_number').first()
        return (last.attempt_number + 1) if last else 1


class BasicFactsResult(models.Model):
    """Result for a Basic Facts quiz attempt (questions are runtime-generated)."""
    SUBTOPIC_CHOICES = [
        ('Addition', 'Addition'),
        ('Subtraction', 'Subtraction'),
        ('Multiplication', 'Multiplication'),
        ('Division', 'Division'),
        ('PlaceValue', 'Place Value Facts'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='basic_facts_results',
    )
    subtopic = models.CharField(max_length=20, choices=SUBTOPIC_CHOICES)
    level_number = models.PositiveIntegerField()
    session_id = models.UUIDField(default=uuid.uuid4, unique=True)
    score = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=10)
    points = models.FloatField(default=0.0)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    questions_data = models.JSONField(
        default=list,
        help_text='Stores generated questions + student answers for review.',
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']
        indexes = [
            models.Index(fields=['student', 'subtopic', 'level_number']),
        ]

    def __str__(self):
        return f'{self.student.username} — {self.subtopic} L{self.level_number} — {self.points:.1f}pts'

    @property
    def percentage(self):
        if self.total_questions == 0:
            return 0
        return round((self.score / self.total_questions) * 100)

    @classmethod
    def get_best_result(cls, student, subtopic, level_number):
        return cls.objects.filter(
            student=student, subtopic=subtopic, level_number=level_number
        ).order_by('-points').first()


class TopicLevelStatistics(models.Model):
    """Platform-wide statistics per topic-level for colour coding."""
    topic = models.ForeignKey(
        'classroom.Topic',
        on_delete=models.CASCADE,
        related_name='statistics',
    )
    level = models.ForeignKey(
        'classroom.Level',
        on_delete=models.CASCADE,
        related_name='statistics',
    )
    avg_points = models.FloatField(default=0.0)
    sigma = models.FloatField(default=0.0)
    student_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('topic', 'level')

    def __str__(self):
        return f'{self.topic} L{self.level_id}: avg={self.avg_points:.1f} σ={self.sigma:.1f} n={self.student_count}'

    def get_colour_band(self, points):
        """Return Tailwind CSS classes for Indicator B (platform average)."""
        if self.student_count < 2:
            return ''
        avg = self.avg_points
        s = self.sigma
        if s == 0:
            return 'bg-green-200 text-green-900'
        if points > avg + 2 * s:
            return 'bg-green-800 text-white'
        if points > avg + s:
            return 'bg-green-500 text-white'
        if points > avg - s:
            return 'bg-green-200 text-green-900'
        if points > avg - 2 * s:
            return 'bg-yellow-200 text-yellow-900'
        if points > avg - 3 * s:
            return 'bg-orange-200 text-orange-900'
        return 'bg-red-200 text-red-900'


class TimeLog(models.Model):
    """Daily and weekly time-on-task tracking per student."""
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='time_log',
    )
    daily_seconds = models.PositiveIntegerField(default=0)
    weekly_seconds = models.PositiveIntegerField(default=0)
    last_daily_reset = models.DateField(null=True, blank=True)
    last_weekly_reset = models.DateField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.student.username} — daily:{self.daily_seconds}s weekly:{self.weekly_seconds}s'
