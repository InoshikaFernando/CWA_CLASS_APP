import secrets

from django.db import models
from django.db.models import F
from django.conf import settings
from django.utils import timezone


# ---------------------------------------------------------------------------
# Join-code helpers (defined here to avoid circular imports with utils.py)
# ---------------------------------------------------------------------------

_JOIN_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
_JOIN_CODE_LENGTH = 6


def generate_join_code() -> str:
    """Generate a unique 6-char alphanumeric join code, retrying on collision."""
    for _ in range(10):
        code = ''.join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(_JOIN_CODE_LENGTH))
        if not BrainBuzzSession.objects.filter(code=code).exists():
            return code
    raise RuntimeError('Could not generate a unique join code after 10 attempts.')


# ---------------------------------------------------------------------------
# Question-type constants (shared between BrainBuzzSessionQuestion and
# the CodingExercise/MathsQuestion extensions so the pipeline stays consistent)
# ---------------------------------------------------------------------------

QUESTION_TYPE_MCQ = 'mcq'
QUESTION_TYPE_TRUE_FALSE = 'tf'
QUESTION_TYPE_SHORT_ANSWER = 'short'
QUESTION_TYPE_FILL_BLANK = 'fill_blank'

# Compat alias used by older test files
QUESTION_TYPE_MULTIPLE_CHOICE = QUESTION_TYPE_MCQ

QUIZ_QUESTION_TYPE_CHOICES = [
    (QUESTION_TYPE_MCQ, 'Multiple Choice'),
    (QUESTION_TYPE_TRUE_FALSE, 'True / False'),
    (QUESTION_TYPE_SHORT_ANSWER, 'Short Answer'),
    (QUESTION_TYPE_FILL_BLANK, 'Fill in the Blank'),
]


# ---------------------------------------------------------------------------
# BrainBuzzSession
# ---------------------------------------------------------------------------

class BrainBuzzSession(models.Model):
    """A live quiz session created by a teacher.
    
    Denormalized session state for fast reads:
    - code: unique join code
    - host: teacher running the session
    - subject: FK to classroom.Subject
    - status: lobby, active, between (questions), finished, cancelled
    - current_index: 0-based position in questions list
    - state_version: incremented on every state change (for cache invalidation)
    - question_deadline: UTC end time for the current question
    - time_per_question_sec: default time per question
    """

    STATUS_LOBBY = 'lobby'
    STATUS_ACTIVE = 'active'
    STATUS_REVEAL = 'reveal'
    STATUS_BETWEEN = 'between'
    STATUS_FINISHED = 'finished'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_LOBBY, 'Lobby'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_REVEAL, 'Reveal'),
        (STATUS_BETWEEN, 'Between Questions'),
        (STATUS_FINISHED, 'Finished'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    code = models.CharField(
        max_length=6,
        unique=True,
        db_index=True,
        help_text='6-character alphanumeric join code (A-Z, 2-9; no 0/O/1/I/L)',
    )
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='brainbuzz_sessions_hosted',
    )
    subject = models.ForeignKey(
        'classroom.Subject',
        on_delete=models.CASCADE,
        related_name='brainbuzz_sessions',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_LOBBY,
        db_index=True,
    )
    current_index = models.IntegerField(default=0)
    state_version = models.IntegerField(default=0)
    question_deadline = models.DateTimeField(null=True, blank=True)
    time_per_question_sec = models.IntegerField(default=20)
    config_json = models.JSONField(
        default=dict,
        blank=True,
        help_text='Session creation params stored for the "repeat session" feature.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['code', 'status'], name='bb_session_code_status_idx'),
            models.Index(fields=['host', 'created_at'], name='bb_session_host_created_idx'),
        ]

    # Compat aliases for legacy test files
    LOBBY = STATUS_LOBBY
    IN_PROGRESS = STATUS_ACTIVE
    ENDED = STATUS_FINISHED

    @property
    def current_question_index(self):
        return self.current_index

    @current_question_index.setter
    def current_question_index(self, value):
        self.current_index = value

    def bump_version(self):
        BrainBuzzSession.objects.filter(pk=self.pk).update(state_version=F('state_version') + 1)
        self.refresh_from_db()

    def __str__(self):
        return f"BrainBuzz {self.code} [{self.get_status_display()}] — {self.host.username}"


# ---------------------------------------------------------------------------
# BrainBuzzSessionQuestion
# ---------------------------------------------------------------------------

class BrainBuzzSessionQuestion(models.Model):
    """Snapshot of a question for a specific BrainBuzz session.

    Questions are copied at session creation time so edits to source questions
    never affect running sessions. This denormalization ensures session integrity.
    
    For MCQ/TF questions:
    - options_json: [{"label":"A","text":"...","is_correct":true/false}, ...]
    
    For short-answer/fill-blank questions:
    - correct_short_answer: canonical answer string
    - options_json: empty list
    """

    session = models.ForeignKey(
        BrainBuzzSession,
        on_delete=models.CASCADE,
        related_name='questions',
    )
    order = models.IntegerField()
    question_text = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QUIZ_QUESTION_TYPE_CHOICES,
        default=QUESTION_TYPE_MCQ,
    )
    options_json = models.JSONField(
        default=list,
        blank=True,
        help_text='MCQ/TF options: [{"label":"A","text":"...","is_correct":true}]',
    )
    correct_short_answer = models.TextField(null=True, blank=True)
    explanation = models.TextField(blank=True)
    points_base = models.IntegerField(default=1000)
    source_model = models.CharField(
        max_length=100,
        help_text='Source model name (e.g., "CodingExercise", "MathsQuestion")',
    )
    source_id = models.IntegerField(help_text='Source primary key for analytics')

    class Meta:
        ordering = ['session', 'order']
        unique_together = ('session', 'order')
        indexes = [
            models.Index(fields=['session', 'order'], name='bb_sq_session_order_idx'),
        ]

    def __str__(self):
        return f"Q{self.order} [{self.session.code}]: {self.question_text[:60]}"


# ---------------------------------------------------------------------------
# BrainBuzzParticipant
# ---------------------------------------------------------------------------

class BrainBuzzParticipant(models.Model):
    """A student (authenticated or anonymous) who has joined a session."""

    session = models.ForeignKey(
        BrainBuzzSession,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='brainbuzz_participations',
    )
    nickname = models.CharField(max_length=255)
    joined_at = models.DateTimeField(auto_now_add=True)
    score = models.IntegerField(default=0)
    last_correct_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp of last correct answer (used for tie-breaking in rankings)',
    )

    class Meta:
        ordering = ['-score', 'joined_at']
        constraints = [
            models.UniqueConstraint(fields=['session', 'nickname'], name='unique_session_nickname'),
        ]
        indexes = [
            models.Index(fields=['session', 'nickname'], name='bb_part_session_nick_idx'),
        ]

    def __str__(self):
        return f"{self.nickname} in {self.session.code} ({self.score} pts)"


# ---------------------------------------------------------------------------
# BrainBuzzAnswer
# ---------------------------------------------------------------------------

class BrainBuzzAnswer(models.Model):
    """One answer submitted by a participant for one session question."""

    participant = models.ForeignKey(
        BrainBuzzParticipant,
        on_delete=models.CASCADE,
        related_name='answers',
    )
    session_question = models.ForeignKey(
        BrainBuzzSessionQuestion,
        on_delete=models.CASCADE,
        related_name='answers',
    )
    selected_option_label = models.CharField(
        max_length=1,
        null=True,
        blank=True,
        help_text='For MCQ/TF: "A", "B", "C", "D", "T", "F", etc.',
    )
    short_answer_text = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    time_taken_ms = models.IntegerField()
    points_awarded = models.IntegerField(default=0)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ['-submitted_at']
        constraints = [
            models.UniqueConstraint(fields=['participant', 'session_question'], name='unique_participant_question'),
        ]
        indexes = [
            models.Index(fields=['session_question', 'participant'], name='bb_ans_sq_part_idx'),
            models.Index(fields=['is_correct'], name='bb_ans_is_correct_idx'),
        ]

    def __str__(self):
        result = "✓" if self.is_correct else "✗"
        return f"{self.participant.nickname} — Q{self.session_question.order} [{result}] {self.points_awarded}pts"


# ---------------------------------------------------------------------------
# BrainBuzzQuiz  (teacher-created custom quizzes — Quiz Builder)
# ---------------------------------------------------------------------------

class BrainBuzzQuiz(models.Model):
    """A teacher-created quiz that can be launched as a BrainBuzz session."""

    title = models.CharField(max_length=255)
    subject = models.ForeignKey(
        'classroom.Subject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='brainbuzz_quizzes',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='brainbuzz_quizzes',
    )
    is_draft = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['created_by', 'is_draft'], name='bb_quiz_creator_draft_idx'),
        ]

    def __str__(self):
        prefix = '[DRAFT] ' if self.is_draft else ''
        return f"{prefix}{self.title}"

    @property
    def question_count(self):
        return self.quiz_questions.count()

    def is_valid_for_publish(self):
        """Valid if at least 1 question exists and every MCQ/TF has ≥1 correct option."""
        if not self.quiz_questions.exists():
            return False
        for q in self.quiz_questions.all():
            if q.question_type in (QUESTION_TYPE_MCQ, QUESTION_TYPE_TRUE_FALSE):
                if not q.quiz_options.filter(is_correct=True).exists():
                    return False
        return True


class BrainBuzzQuizQuestion(models.Model):
    """A question inside a teacher-created BrainBuzz quiz."""

    quiz = models.ForeignKey(
        BrainBuzzQuiz,
        on_delete=models.CASCADE,
        related_name='quiz_questions',
    )
    question_text = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QUIZ_QUESTION_TYPE_CHOICES,
        default=QUESTION_TYPE_MCQ,
    )
    time_limit = models.IntegerField(
        default=20,
        help_text='Seconds allocated for this question when played live.',
    )
    order = models.IntegerField(default=0)
    correct_short_answer = models.TextField(
        null=True,
        blank=True,
        help_text='Correct answer text for short-answer / fill-blank types.',
    )

    class Meta:
        ordering = ['quiz', 'order']
        indexes = [
            models.Index(fields=['quiz', 'order'], name='bb_qq_quiz_order_idx'),
        ]

    def __str__(self):
        return f"Q{self.order + 1}: {self.question_text[:60]}"


class BrainBuzzQuizOption(models.Model):
    """An answer option for a BrainBuzzQuizQuestion (MCQ / True-False)."""

    question = models.ForeignKey(
        BrainBuzzQuizQuestion,
        on_delete=models.CASCADE,
        related_name='quiz_options',
    )
    option_text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['question', 'order']
        indexes = [
            models.Index(fields=['question', 'order'], name='bb_qo_question_order_idx'),
        ]

    def __str__(self):
        mark = '✓ ' if self.is_correct else ''
        return f"{mark}{self.option_text[:40]}"


# ---------------------------------------------------------------------------
# Compat helper — used by older test files
# ---------------------------------------------------------------------------

def calculate_brainbuzz_score(time_limit_sec: int, time_remaining_sec: float) -> int:
    """Legacy signature: (time_limit, time_remaining) → points (0–1000).

    Wraps scoring.calculate_points with the time-remaining convention used
    by earlier test files. Returns 0 when time_remaining_sec <= 0.
    """
    if time_limit_sec <= 0 or time_remaining_sec <= 0:
        return 0
    from .scoring import calculate_points
    time_taken_ms = max(0, int((time_limit_sec - time_remaining_sec) * 1000))
    return calculate_points(True, time_taken_ms, time_limit_sec, 1000)
