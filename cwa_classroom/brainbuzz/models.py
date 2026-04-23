import secrets
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


# ---------------------------------------------------------------------------
# Join-code generation
# ---------------------------------------------------------------------------

# Omit visually ambiguous characters: 0/O, 1/I/L
_JOIN_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
_JOIN_CODE_LENGTH = 6


def generate_join_code():
    """Generate a unique 6-character join code, retrying on collision."""
    for _ in range(10):
        code = ''.join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(_JOIN_CODE_LENGTH))
        if not BrainBuzzSession.objects.filter(
            join_code=code,
            state__in=[BrainBuzzSession.LOBBY, BrainBuzzSession.IN_PROGRESS],
        ).exists():
            return code
    raise RuntimeError("Could not generate a unique join code after 10 attempts.")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_SCORE_MAX = 1000
_SCORE_MIN = 500


def calculate_brainbuzz_score(time_limit_seconds: int, seconds_remaining: float) -> int:
    """Time-bonus score for a correct answer.

    Correct at deadline  → _SCORE_MIN (500)
    Correct instantly    → _SCORE_MAX (1000)
    Incorrect / too late → 0
    """
    if seconds_remaining <= 0 or time_limit_seconds <= 0:
        return 0
    fraction = max(0.0, min(1.0, seconds_remaining / time_limit_seconds))
    return round(_SCORE_MIN + (_SCORE_MAX - _SCORE_MIN) * fraction)


# ---------------------------------------------------------------------------
# Question-type constants (shared between BrainBuzzSessionQuestion and
# the CodingExercise extension so the pipeline stays consistent)
# ---------------------------------------------------------------------------

QUESTION_TYPE_MULTIPLE_CHOICE = 'multiple_choice'
QUESTION_TYPE_TRUE_FALSE = 'true_false'
QUESTION_TYPE_SHORT_ANSWER = 'short_answer'
QUESTION_TYPE_FILL_BLANK = 'fill_blank'
QUESTION_TYPE_WRITE_CODE = 'write_code'

QUIZ_QUESTION_TYPE_CHOICES = [
    (QUESTION_TYPE_MULTIPLE_CHOICE, 'Multiple Choice'),
    (QUESTION_TYPE_TRUE_FALSE, 'True / False'),
    (QUESTION_TYPE_SHORT_ANSWER, 'Short Answer'),
    (QUESTION_TYPE_FILL_BLANK, 'Fill in the Blank'),
]


# ---------------------------------------------------------------------------
# BrainBuzzSession
# ---------------------------------------------------------------------------

class BrainBuzzSession(models.Model):
    """A live quiz session created by a teacher."""

    LOBBY = 'lobby'
    IN_PROGRESS = 'in_progress'
    ENDED = 'ended'

    STATE_CHOICES = [
        (LOBBY, 'Lobby'),
        (IN_PROGRESS, 'In Progress'),
        (ENDED, 'Ended'),
    ]

    SUBJECT_MATHS = 'maths'
    SUBJECT_CODING = 'coding'

    SUBJECT_CHOICES = [
        (SUBJECT_MATHS, 'Maths'),
        (SUBJECT_CODING, 'Coding'),
    ]

    join_code = models.CharField(max_length=6, unique=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='brainbuzz_sessions',
    )
    subject = models.CharField(max_length=20, choices=SUBJECT_CHOICES)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=LOBBY, db_index=True)
    state_version = models.PositiveIntegerField(default=0)
    current_question_index = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['join_code', 'state'], name='bb_session_code_state_idx'),
        ]

    def __str__(self):
        return f"BrainBuzz {self.join_code} [{self.get_state_display()}] — {self.created_by}"

    def bump_version(self):
        """Increment state_version and save. Call inside transactions after state changes."""
        self.state_version += 1
        self.save(update_fields=['state_version', 'state', 'current_question_index', 'updated_at'])

    @property
    def active_participants(self):
        return self.participants.filter(is_active=True)

    @property
    def current_question(self):
        if self.current_question_index is None:
            return None
        return self.questions.filter(order_index=self.current_question_index).first()

    def leaderboard(self):
        """Return participants sorted by total_score desc, joined_at asc (stable tie-break)."""
        return self.participants.filter(is_active=True).order_by('-total_score', 'joined_at')


# ---------------------------------------------------------------------------
# BrainBuzzSessionQuestion
# ---------------------------------------------------------------------------

class BrainBuzzSessionQuestion(models.Model):
    """Snapshot of a question for a specific BrainBuzz session.

    Questions are copied at session creation time so edits to source questions
    never affect running sessions.
    """

    session = models.ForeignKey(
        BrainBuzzSession,
        on_delete=models.CASCADE,
        related_name='questions',
    )
    order_index = models.PositiveSmallIntegerField()
    question_text = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QUIZ_QUESTION_TYPE_CHOICES,
        default=QUESTION_TYPE_MULTIPLE_CHOICE,
    )
    # For MCQ/TF: list of {"id": str, "text": str, "is_correct": bool}
    options = models.JSONField(default=list, blank=True)
    # For short_answer/fill_blank: accepted answer strings (case-insensitive)
    accepted_answers = models.JSONField(default=list, blank=True)
    time_limit_seconds = models.PositiveSmallIntegerField(default=20)
    question_start_time_utc = models.DateTimeField(null=True, blank=True)
    question_deadline_utc = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['session', 'order_index']
        unique_together = ('session', 'order_index')
        indexes = [
            models.Index(fields=['session', 'order_index'], name='bb_sq_session_order_idx'),
        ]

    def __str__(self):
        return f"Q{self.order_index + 1} [{self.session.join_code}]: {self.question_text[:60]}"

    def start(self):
        """Record start + deadline times for this question."""
        now = timezone.now()
        self.question_start_time_utc = now
        self.question_deadline_utc = now + timedelta(seconds=self.time_limit_seconds)
        self.save(update_fields=['question_start_time_utc', 'question_deadline_utc'])

    def is_submission_on_time(self, submitted_at):
        """True if submission arrived within the 500ms grace period."""
        if self.question_deadline_utc is None:
            return False
        grace = self.question_deadline_utc + timedelta(milliseconds=500)
        return submitted_at <= grace

    @property
    def correct_option_ids(self):
        """IDs of correct options for MCQ/TF questions."""
        return [opt['id'] for opt in self.options if opt.get('is_correct')]

    def check_answer(self, answer_payload: dict) -> bool:
        """Return True if the submitted answer_payload is correct."""
        if self.question_type in (QUESTION_TYPE_MULTIPLE_CHOICE, QUESTION_TYPE_TRUE_FALSE):
            submitted = answer_payload.get('option_id', '')
            return submitted in self.correct_option_ids

        if self.question_type in (QUESTION_TYPE_SHORT_ANSWER, QUESTION_TYPE_FILL_BLANK):
            submitted = answer_payload.get('text', '').strip().lower()
            return any(submitted == a.strip().lower() for a in self.accepted_answers)

        return False


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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='brainbuzz_participations',
    )
    nickname = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    total_score = models.PositiveIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-total_score', 'joined_at']
        indexes = [
            models.Index(fields=['session', 'nickname'], name='bb_part_session_nick_idx'),
        ]

    def __str__(self):
        return f"{self.nickname} in {self.session.join_code} ({self.total_score} pts)"

    @classmethod
    def resolve_nickname(cls, session, desired_nickname: str) -> str:
        """Return desired_nickname, or suffixed variant if already taken in this session."""
        existing = set(
            cls.objects.filter(session=session, is_active=True)
            .values_list('nickname', flat=True)
        )
        if desired_nickname not in existing:
            return desired_nickname
        counter = 2
        while f"{desired_nickname}#{counter}" in existing:
            counter += 1
        return f"{desired_nickname}#{counter}"


# ---------------------------------------------------------------------------
# BrainBuzzSubmission
# ---------------------------------------------------------------------------

class BrainBuzzSubmission(models.Model):
    """One answer submitted by a participant for one session question."""

    participant = models.ForeignKey(
        BrainBuzzParticipant,
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    session_question = models.ForeignKey(
        BrainBuzzSessionQuestion,
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    answer_payload = models.JSONField(help_text='{"option_id": "..."} or {"text": "..."}')
    is_correct = models.BooleanField(default=False)
    score_awarded = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('participant', 'session_question')
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['session_question', 'participant'], name='bb_sub_sq_part_idx'),
        ]

    def __str__(self):
        result = "CORRECT" if self.is_correct else "WRONG"
        return f"{self.participant.nickname} — Q{self.session_question.order_index + 1} [{result}] {self.score_awarded}pts"
