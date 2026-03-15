import hashlib
import json
import uuid

from django.db import models


class NumberPuzzleLevel(models.Model):
    """A difficulty level for number puzzles. Seeded data, not user-editable."""

    number = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    operators_allowed = models.CharField(max_length=20)
    min_operand = models.PositiveIntegerField(default=1)
    max_operand = models.PositiveIntegerField(default=9)
    num_operands = models.PositiveIntegerField(default=2)
    brackets_shown = models.BooleanField(default=False)
    brackets_required = models.BooleanField(default=False)
    nested_brackets = models.BooleanField(default=False)
    puzzles_per_set = models.PositiveIntegerField(default=10)
    unlock_threshold = models.PositiveIntegerField(default=8)
    max_result = models.PositiveIntegerField(default=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['number']

    def __str__(self):
        return f"Level {self.number}: {self.name}"


class NumberPuzzle(models.Model):
    """A pre-generated number puzzle. Global scope."""

    level = models.ForeignKey(
        NumberPuzzleLevel,
        on_delete=models.CASCADE,
        related_name='puzzles'
    )
    operands = models.JSONField()
    operands_hash = models.CharField(max_length=32, editable=False)
    target = models.IntegerField()
    display_template = models.CharField(max_length=200)
    solution = models.CharField(max_length=200)
    has_multiple_solutions = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('level', 'operands_hash', 'target')
        ordering = ['level', 'id']

    def __str__(self):
        return f"L{self.level.number}: {self.display_template}"

    def save(self, *args, **kwargs):
        self.operands_hash = hashlib.md5(
            json.dumps(self.operands, sort_keys=False).encode()
        ).hexdigest()
        super().save(*args, **kwargs)


class PuzzleSession(models.Model):
    """A student's attempt at a set of puzzles at a given level."""

    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='puzzle_sessions'
    )
    level = models.ForeignKey(
        NumberPuzzleLevel,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    score = models.PositiveIntegerField(default=0)
    total_questions = models.PositiveIntegerField(default=10)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.student} - Level {self.level.number} ({self.score}/{self.total_questions})"


class PuzzleAttempt(models.Model):
    """A student's answer to a single puzzle within a session."""

    session = models.ForeignKey(
        PuzzleSession,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    puzzle = models.ForeignKey(
        NumberPuzzle,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    question_number = models.PositiveIntegerField()
    student_answer = models.CharField(max_length=200)
    is_correct = models.BooleanField(default=False)
    time_taken_seconds = models.PositiveIntegerField(null=True, blank=True)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'question_number')
        ordering = ['question_number']

    def __str__(self):
        return f"Q{self.question_number}: {'✓' if self.is_correct else '✗'}"


class SessionPuzzle(models.Model):
    """Pre-selected puzzle queue for a session."""

    session = models.ForeignKey(
        PuzzleSession,
        on_delete=models.CASCADE,
        related_name='session_puzzles'
    )
    puzzle = models.ForeignKey(
        NumberPuzzle,
        on_delete=models.CASCADE,
        related_name='session_assignments'
    )
    question_number = models.PositiveIntegerField()

    class Meta:
        unique_together = ('session', 'question_number')
        ordering = ['question_number']

    def __str__(self):
        return f"Session {self.session_id} Q{self.question_number}"


class StudentPuzzleProgress(models.Model):
    """Tracks a student's overall progress for each puzzle level."""

    student = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='puzzle_progress'
    )
    level = models.ForeignKey(
        NumberPuzzleLevel,
        on_delete=models.CASCADE,
        related_name='student_progress'
    )
    is_unlocked = models.BooleanField(default=False)
    best_score = models.PositiveIntegerField(default=0)
    best_time_seconds = models.PositiveIntegerField(null=True, blank=True)
    total_sessions = models.PositiveIntegerField(default=0)
    total_puzzles_attempted = models.PositiveIntegerField(default=0)
    total_puzzles_correct = models.PositiveIntegerField(default=0)
    last_played_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('student', 'level')
        ordering = ['level__number']

    def __str__(self):
        return f"{self.student} - Level {self.level.number}: {self.best_score}"

    @property
    def stars(self):
        if self.best_score >= 10:
            return 3
        elif self.best_score >= 8:
            return 2
        elif self.best_score >= 5:
            return 1
        return 0

    @property
    def accuracy(self):
        if self.total_puzzles_attempted == 0:
            return 0
        return round((self.total_puzzles_correct / self.total_puzzles_attempted) * 100)
