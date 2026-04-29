"""
Unit tests for BrainBuzz Wizard functionality.

Test coverage:
- WizardState serialization/deserialization
- BrainBuzzFilter question counting and filtering
- Filter validation (can_create, count_matching)
- Preview sampling
- Duration estimation
- Edge cases (empty filters, too few questions, etc.)
"""

from django.test import TestCase

from classroom.models import Topic, Level, Subject
from maths.models import Question, Answer

from brainbuzz.wizard import WizardState, BrainBuzzFilter


class WizardStateTestCase(TestCase):
    """Test WizardState serialization and validation."""

    def test_initialization_with_defaults(self):
        """Test WizardState initializes with sensible defaults."""
        state = WizardState()
        self.assertIsNone(state.subject)
        self.assertEqual(state.topic_ids, [])
        self.assertEqual(state.level_ids, [])
        self.assertEqual(state.difficulty, 2)
        self.assertEqual(state.num_questions, 10)
        self.assertEqual(state.time_per_question_sec, 20)

    def test_to_dict_serialization(self):
        """Test conversion to dict for JSON serialization."""
        state = WizardState(
            subject="maths",
            topic_ids=[1, 2],
            level_ids=[3, 4],
            difficulty=3,
            num_questions=15,
            time_per_question_sec=30,
        )
        data = state.to_dict()
        self.assertEqual(data["subject"], "maths")
        self.assertEqual(data["topic_ids"], [1, 2])
        self.assertEqual(data["level_ids"], [3, 4])
        self.assertEqual(data["difficulty"], 3)
        self.assertEqual(data["num_questions"], 15)
        self.assertEqual(data["time_per_question_sec"], 30)

    def test_from_dict_deserialization(self):
        """Test reconstruction from dict."""
        data = {
            "subject": "coding",
            "topic_ids": [5, 6],
            "level_ids": [7],
            "difficulty": 1,
            "num_questions": 5,
            "time_per_question_sec": 60,
        }
        state = WizardState.from_dict(data)
        self.assertEqual(state.subject, "coding")
        self.assertEqual(state.topic_ids, [5, 6])
        self.assertEqual(state.difficulty, 1)

    def test_round_trip_serialization(self):
        """Test serialize → deserialize → serialize produces same result."""
        original = WizardState(
            subject="maths",
            topic_ids=[1, 2, 3],
            level_ids=[10, 20],
            difficulty=2,
            num_questions=12,
            time_per_question_sec=25,
        )
        data = original.to_dict()
        reconstructed = WizardState.from_dict(data)
        self.assertEqual(reconstructed.to_dict(), data)

    def test_is_complete_requires_subject(self):
        """Wizard incomplete without subject."""
        state = WizardState(topic_ids=[1])
        self.assertFalse(state.is_complete())

    def test_is_complete_requires_topic_or_level(self):
        """Wizard incomplete without topic/level filter."""
        state = WizardState(subject="maths")
        self.assertFalse(state.is_complete())

    def test_is_complete_with_all_fields(self):
        """Wizard complete with all required fields."""
        state = WizardState(
            subject="maths",
            topic_ids=[1],
            num_questions=10,
        )
        self.assertTrue(state.is_complete())

    def test_is_complete_with_levels_only(self):
        """Wizard complete with level filter (no topics)."""
        state = WizardState(
            subject="coding",
            level_ids=[5],
            num_questions=10,
        )
        self.assertTrue(state.is_complete())


class BrainBuzzFilterTestCase(TestCase):
    """Test BrainBuzzFilter logic."""

    @classmethod
    def setUpTestData(cls):
        """Create test data."""
        cls.subject = Subject.objects.get_or_create(
            slug='wizard-test', defaults={'name': 'Wizard Test'},
        )[0]

        cls.topic1 = Topic.objects.create(name="Arithmetic", slug="wizard-arith", subject=cls.subject)
        cls.topic2 = Topic.objects.create(name="Fractions", slug="wizard-frac", subject=cls.subject)

        cls.level1 = Level.objects.create(level_number=901, display_name="Wizard L1")
        cls.level2 = Level.objects.create(level_number=902, display_name="Wizard L2")

        # Create 5 MCQ math questions in topic1/level1
        for i in range(5):
            q = Question.objects.create(
                topic=cls.topic1,
                level=cls.level1,
                question_text=f"Math Q{i}",
                question_type="multiple_choice",
            )
            Answer.objects.create(
                question=q,
                answer_text="Answer 1",
                is_correct=True,
                order=0,
            )

        # Create 3 True/False questions in topic2/level2
        for i in range(3):
            q = Question.objects.create(
                topic=cls.topic2,
                level=cls.level2,
                question_text=f"Fraction Q{i}",
                question_type="true_false",
            )
            Answer.objects.create(
                question=q,
                answer_text="True",
                is_correct=True,
                order=0,
            )

    def test_empty_filter_returns_no_questions(self):
        """Filter with no subject returns 0 questions."""
        state = WizardState()
        filter_obj = BrainBuzzFilter(state)
        self.assertEqual(filter_obj.count_matching_questions(), 0)

    def test_filter_by_topic(self):
        """Filter questions by topic."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic1.id],
        )
        filter_obj = BrainBuzzFilter(state)
        count = filter_obj.count_matching_questions()
        self.assertEqual(count, 5)

    def test_filter_by_level(self):
        """Filter questions by level."""
        state = WizardState(
            subject="maths",
            level_ids=[self.level2.id],
        )
        filter_obj = BrainBuzzFilter(state)
        count = filter_obj.count_matching_questions()
        self.assertEqual(count, 3)

    def test_filter_by_multiple_topics(self):
        """Filter by multiple topics (OR logic)."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic1.id, self.topic2.id],
        )
        filter_obj = BrainBuzzFilter(state)
        count = filter_obj.count_matching_questions()
        self.assertEqual(count, 8)  # 5 + 3

    def test_can_create_insufficient_questions(self):
        """can_create returns False when not enough questions."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic2.id],  # Only 3 questions
            num_questions=10,  # Needs 10
        )
        filter_obj = BrainBuzzFilter(state)
        can_create, message = filter_obj.can_create()
        self.assertFalse(can_create)
        self.assertIn("3 questions", message)
        self.assertIn("10", message)

    def test_can_create_sufficient_questions(self):
        """can_create returns True with enough questions."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic1.id],  # 5 questions
            num_questions=3,  # Only needs 3
        )
        filter_obj = BrainBuzzFilter(state)
        can_create, message = filter_obj.can_create()
        self.assertTrue(can_create)
        self.assertIsNone(message)

    def test_can_create_incomplete_state(self):
        """can_create returns False for incomplete wizard state."""
        state = WizardState(
            subject="maths",
            # No filters
            num_questions=10,
        )
        filter_obj = BrainBuzzFilter(state)
        can_create, message = filter_obj.can_create()
        self.assertFalse(can_create)

    def test_preview_sampling(self):
        """Preview returns first N questions."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic1.id],
        )
        filter_obj = BrainBuzzFilter(state)
        preview = filter_obj.sample_preview(num=2)
        self.assertEqual(len(preview), 2)
        self.assertIn("id", preview[0])
        self.assertIn("text", preview[0])
        self.assertIn("type", preview[0])

    def test_estimate_duration(self):
        """Duration estimation is correct."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic1.id],
            num_questions=10,
            time_per_question_sec=20,
        )
        filter_obj = BrainBuzzFilter(state)
        duration = filter_obj.estimate_duration_sec()
        self.assertEqual(duration, 200)  # 10 * 20

    def test_estimate_duration_different_times(self):
        """Duration respects custom time per question."""
        state = WizardState(
            subject="maths",
            topic_ids=[self.topic1.id],
            num_questions=5,
            time_per_question_sec=60,
        )
        filter_obj = BrainBuzzFilter(state)
        duration = filter_obj.estimate_duration_sec()
        self.assertEqual(duration, 300)  # 5 * 60

    def test_invalid_subject_returns_empty(self):
        """Invalid subject returns 0 questions."""
        state = WizardState(
            subject="invalid_subject",
            topic_ids=[1],
        )
        filter_obj = BrainBuzzFilter(state)
        count = filter_obj.count_matching_questions()
        self.assertEqual(count, 0)

    def test_no_filters_returns_empty(self):
        """No topic/level filters returns empty."""
        state = WizardState(subject="maths")
        filter_obj = BrainBuzzFilter(state)
        count = filter_obj.count_matching_questions()
        self.assertEqual(count, 0)
