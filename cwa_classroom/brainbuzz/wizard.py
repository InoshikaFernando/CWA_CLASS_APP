"""
BrainBuzz Wizard — Multi-step session creation with live filtering.

Features:
- Subject selection (Maths/Coding with tiles)
- Multi-select topics + levels (chips) with live question count
- Difficulty (1-3) and size (5/10/15/20) controls
- Time per question customization (10/20/30/60 sec)
- Question preview (first 3 sampled) with estimated duration
- Session storage persistence (survives back-nav)
- Mobile-responsive UI

Architecture:
- WizardState: Manages form state across steps, JSON-serializable
- BrainBuzzFilter: Question filtering and validation logic
- Views: HTTP endpoints for wizard steps and AJAX filtering

Goal: Create session in < 30 seconds
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional

from django.db.models import Q, QuerySet

from .models import (
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_FILL_BLANK,
)


# Question types eligible for BrainBuzz
BRAINBUZZ_QUESTION_TYPES = {
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_FILL_BLANK,
}


@dataclass
class WizardState:
    """Wizard form state — persists via session storage."""

    subject: Optional[str] = None
    topic_ids: List[int] = None
    level_ids: List[int] = None
    difficulty: int = 2
    num_questions: int = 10
    time_per_question_sec: int = 20

    def __post_init__(self):
        if self.topic_ids is None:
            self.topic_ids = []
        if self.level_ids is None:
            self.level_ids = []

    def to_dict(self) -> Dict:
        """Serialize to JSON-compatible dict for session storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "WizardState":
        """Deserialize from dict (from session storage)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def is_complete(self) -> bool:
        """Check if wizard state is complete enough to create session."""
        return (
            self.subject
            and (self.topic_ids or self.level_ids)  # At least one filter
            and self.num_questions > 0
        )


class BrainBuzzFilter:
    """Filters questions for BrainBuzz session creation."""

    MIN_QUESTIONS = 5
    MAX_QUESTIONS = 30

    def __init__(self, state: WizardState):
        self.state = state

    def get_questions(self, limit: Optional[int] = None) -> QuerySet:
        """Get filtered questions (matching topic/level filters)."""
        if not self.state.subject:
            return self._empty_qs()

        qs = self._get_subject_questions(self.state.subject)

        # Must have at least one filter
        if not self.state.topic_ids and not self.state.level_ids:
            return self._empty_qs()

        qs = self._apply_topic_level_filters(qs)

        if limit:
            qs = qs[:limit]

        return qs

    def count_matching_questions(self) -> int:
        """Count questions matching all filters."""
        return self.get_questions().count()

    def can_create(self) -> Tuple[bool, Optional[str]]:
        """Validate state for session creation."""
        if not self.state.is_complete():
            return False, "Incomplete wizard state"

        count = self.count_matching_questions()
        if count < self.state.num_questions:
            return (
                False,
                f"Only {count} questions match your filters. Need {self.state.num_questions}.",
            )

        return True, None

    def sample_preview(self, num: int = 3) -> List[Dict]:
        """Preview first N questions for review step."""
        qs = self.get_questions(limit=num)
        return [
            {
                "id": q.id,
                "text": q.question_text[:100],
                "type": q.question_type,
            }
            for q in qs
        ]

    def estimate_duration_sec(self) -> int:
        """Estimate session duration (questions * time per question)."""
        return self.state.num_questions * self.state.time_per_question_sec

    # ---- Private ----

    @staticmethod
    def _empty_qs() -> QuerySet:
        """Return empty QuerySet."""
        from maths.models import Question
        return Question.objects.none()

    def _get_subject_questions(self, subject: str) -> QuerySet:
        """Get question QuerySet for subject."""
        if subject == "maths":
            from maths.models import Question
            return Question.objects.for_brainbuzz()
        elif subject == "coding":
            from coding.models import CodingExercise
            return CodingExercise.objects.for_brainbuzz()
        else:
            return self._empty_qs()

    def _apply_topic_level_filters(self, qs: QuerySet) -> QuerySet:
        """Filter by topic and/or level (OR logic)."""
        q_filter = Q()

        if self.state.topic_ids:
            if "maths" in str(qs.model):
                q_filter |= Q(topic_id__in=self.state.topic_ids)
            else:
                q_filter |= Q(topic_level__topic_id__in=self.state.topic_ids)

        if self.state.level_ids:
            if "maths" in str(qs.model):
                q_filter |= Q(level_id__in=self.state.level_ids)
            else:
                q_filter |= Q(topic_level__level_id__in=self.state.level_ids)

        return qs.filter(q_filter) if q_filter else qs
