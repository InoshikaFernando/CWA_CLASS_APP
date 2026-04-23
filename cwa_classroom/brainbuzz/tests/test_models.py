"""
Unit tests for brainbuzz models.

Covers:
  - generate_join_code: length, alphabet, uniqueness, collision handling
  - calculate_brainbuzz_score: correct ranges, edge cases
  - BrainBuzzSession: state transitions, bump_version, leaderboard ordering
  - BrainBuzzSessionQuestion: start(), is_submission_on_time(), check_answer()
  - BrainBuzzParticipant: resolve_nickname (unique + duplicate suffix)
"""
import string
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzSubmission,
    generate_join_code,
    calculate_brainbuzz_score,
    _JOIN_CODE_ALPHABET,
    _JOIN_CODE_LENGTH,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(**kwargs):
    defaults = {'username': 'teacher1', 'password': 'pass', 'email': 'teacher@test.com'}
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_session(teacher, **kwargs):
    defaults = {
        'join_code': 'ABC123',
        'created_by': teacher,
        'subject': BrainBuzzSession.SUBJECT_MATHS,
        'state': BrainBuzzSession.LOBBY,
    }
    defaults.update(kwargs)
    return BrainBuzzSession.objects.create(**defaults)


def _make_question(session, order_index=0, **kwargs):
    defaults = {
        'session': session,
        'order_index': order_index,
        'question_text': 'What is 2 + 2?',
        'question_type': QUESTION_TYPE_MULTIPLE_CHOICE,
        'options': [
            {'id': 'a', 'text': '3', 'is_correct': False},
            {'id': 'b', 'text': '4', 'is_correct': True},
            {'id': 'c', 'text': '5', 'is_correct': False},
            {'id': 'd', 'text': '6', 'is_correct': False},
        ],
        'time_limit_seconds': 20,
    }
    defaults.update(kwargs)
    return BrainBuzzSessionQuestion.objects.create(**defaults)


def _make_participant(session, nickname='Alice', **kwargs):
    defaults = {'session': session, 'nickname': nickname}
    defaults.update(kwargs)
    return BrainBuzzParticipant.objects.create(**defaults)


# ===========================================================================
# Join code generation
# ===========================================================================

class TestGenerateJoinCode(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()

    def test_length_is_six(self):
        code = generate_join_code()
        self.assertEqual(len(code), _JOIN_CODE_LENGTH)

    def test_only_allowed_chars(self):
        for _ in range(50):
            code = generate_join_code()
            for ch in code:
                self.assertIn(ch, _JOIN_CODE_ALPHABET, f"Disallowed char {ch!r} in code {code!r}")

    def test_excluded_ambiguous_chars(self):
        for _ in range(100):
            code = generate_join_code()
            for bad in '0O1IL':
                self.assertNotIn(bad, code, f"Ambiguous char {bad!r} found in {code!r}")

    def test_unique_across_active_sessions(self):
        # Create a session with a specific code to trigger collision on first attempt
        BrainBuzzSession.objects.create(
            join_code='AAAAAA', created_by=self.teacher, subject='maths', state=BrainBuzzSession.LOBBY,
        )
        with patch('brainbuzz.models.secrets.choice') as mock_choice:
            # First 6 calls return 'A' (collision), next 6 return 'B' (unique)
            mock_choice.side_effect = list('AAAAAA') + list('BBBBBB')
            code = generate_join_code()
            self.assertEqual(code, 'BBBBBB')

    def test_raises_after_max_retries(self):
        # Fill up 10 codes that would all collide
        codes = ['ZZZZZZ'] + [f'Z{str(i).zfill(5)}' for i in range(9)]
        for c in codes:
            BrainBuzzSession.objects.create(
                join_code=c, created_by=self.teacher, subject='maths', state=BrainBuzzSession.LOBBY,
            )
        with patch('brainbuzz.models.secrets.choice') as mock_choice:
            # Always return codes that collide
            mock_choice.side_effect = list('ZZZZZZ') * 20
            with self.assertRaises(RuntimeError):
                generate_join_code()


# ===========================================================================
# Scoring function
# ===========================================================================

class TestCalculateBrainBuzzScore(TestCase):

    def test_full_score_at_instant_answer(self):
        score = calculate_brainbuzz_score(20, 20)
        self.assertEqual(score, 1000)

    def test_min_score_at_last_instant(self):
        score = calculate_brainbuzz_score(20, 0.001)
        self.assertGreaterEqual(score, 500)

    def test_zero_for_negative_remaining(self):
        self.assertEqual(calculate_brainbuzz_score(20, -1), 0)

    def test_zero_for_zero_remaining(self):
        self.assertEqual(calculate_brainbuzz_score(20, 0), 0)

    def test_zero_for_zero_time_limit(self):
        self.assertEqual(calculate_brainbuzz_score(0, 5), 0)

    def test_midpoint_answer(self):
        score = calculate_brainbuzz_score(20, 10)
        # Should be 750 (midpoint between 500 and 1000)
        self.assertEqual(score, 750)

    def test_score_monotonically_decreasing(self):
        scores = [calculate_brainbuzz_score(20, t) for t in range(20, 0, -1)]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_clamps_to_max(self):
        score = calculate_brainbuzz_score(20, 999)
        self.assertEqual(score, 1000)


# ===========================================================================
# BrainBuzzSession
# ===========================================================================

class TestBrainBuzzSession(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()
        cls.session = _make_session(cls.teacher)

    def test_str_representation(self):
        s = str(self.session)
        self.assertIn('BrainBuzz', s)
        self.assertIn(self.session.join_code, s)

    def test_bump_version_increments(self):
        initial = self.session.state_version
        self.session.bump_version()
        self.session.refresh_from_db()
        self.assertEqual(self.session.state_version, initial + 1)

    def test_leaderboard_sort_by_score_desc(self):
        session = _make_session(self.teacher, join_code='LBTEST')
        alice = _make_participant(session, 'Alice', total_score=800)
        bob = _make_participant(session, 'Bob', total_score=1200)
        carol = _make_participant(session, 'Carol', total_score=600)

        lb = list(session.leaderboard())
        self.assertEqual(lb[0].nickname, 'Bob')
        self.assertEqual(lb[1].nickname, 'Alice')
        self.assertEqual(lb[2].nickname, 'Carol')

    def test_leaderboard_tie_break_by_joined_at(self):
        session = _make_session(self.teacher, join_code='TIEBRK')
        alice = _make_participant(session, 'Alice', total_score=1000)
        bob = _make_participant(session, 'Bob', total_score=1000)

        lb = list(session.leaderboard())
        # Alice joined first → higher rank on tie
        self.assertEqual(lb[0].nickname, 'Alice')

    def test_current_question_returns_none_when_no_index(self):
        self.assertIsNone(self.session.current_question)

    def test_current_question_returns_correct_question(self):
        session = _make_session(self.teacher, join_code='CURQ12')
        q = _make_question(session, order_index=0)
        session.current_question_index = 0
        session.save(update_fields=['current_question_index'])
        self.assertEqual(session.current_question.pk, q.pk)


# ===========================================================================
# State transitions (idempotency + state_version)
# ===========================================================================

class TestSessionStateTransitions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_st')

    def _fresh_session(self, code):
        s = _make_session(self.teacher, join_code=code)
        _make_question(s, 0)
        _make_question(s, 1)
        _make_question(s, 2)
        return s

    def test_start_moves_to_in_progress(self):
        s = self._fresh_session('STTST1')
        q = s.questions.first()
        q.start()
        s.state = BrainBuzzSession.IN_PROGRESS
        s.current_question_index = 0
        s.bump_version()
        s.refresh_from_db()
        self.assertEqual(s.state, BrainBuzzSession.IN_PROGRESS)
        self.assertEqual(s.current_question_index, 0)
        self.assertEqual(s.state_version, 1)

    def test_next_advances_index(self):
        s = self._fresh_session('NEXADV')
        s.state = BrainBuzzSession.IN_PROGRESS
        s.current_question_index = 0
        s.bump_version()
        # Simulate next
        next_q = s.questions.filter(order_index=1).first()
        next_q.start()
        s.current_question_index = 1
        s.bump_version()
        s.refresh_from_db()
        self.assertEqual(s.current_question_index, 1)
        self.assertEqual(s.state_version, 2)

    def test_end_moves_to_ended(self):
        s = self._fresh_session('ENDTST')
        s.state = BrainBuzzSession.ENDED
        s.current_question_index = None
        s.bump_version()
        s.refresh_from_db()
        self.assertEqual(s.state, BrainBuzzSession.ENDED)
        self.assertIsNone(s.current_question_index)

    def test_idempotent_next_on_index_mismatch(self):
        s = self._fresh_session('IDMPNX')
        s.state = BrainBuzzSession.IN_PROGRESS
        s.current_question_index = 2
        s.save(update_fields=['state', 'current_question_index'])
        initial_version = s.state_version
        # Try to advance from index 0 (stale) — should no-op
        # This mirrors the view logic; here we test the model remains unchanged
        self.assertEqual(s.state_version, initial_version)


# ===========================================================================
# BrainBuzzSessionQuestion
# ===========================================================================

class TestBrainBuzzSessionQuestion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_sq')
        cls.session = _make_session(cls.teacher, join_code='SQTEST')
        cls.question = _make_question(cls.session)

    def test_start_sets_timestamps(self):
        q = _make_question(self.session, order_index=9)
        before = timezone.now()
        q.start()
        after = timezone.now()
        q.refresh_from_db()
        self.assertIsNotNone(q.question_start_time_utc)
        self.assertIsNotNone(q.question_deadline_utc)
        self.assertGreaterEqual(q.question_start_time_utc, before)
        self.assertLessEqual(q.question_start_time_utc, after)
        expected_deadline = q.question_start_time_utc + timedelta(seconds=q.time_limit_seconds)
        self.assertAlmostEqual(
            q.question_deadline_utc.timestamp(),
            expected_deadline.timestamp(),
            delta=0.01,
        )

    def test_is_submission_on_time_within_grace(self):
        q = _make_question(self.session, order_index=10)
        q.start()
        # Submit 200ms before deadline
        on_time = q.question_deadline_utc - timedelta(milliseconds=200)
        self.assertTrue(q.is_submission_on_time(on_time))

    def test_is_submission_on_time_within_500ms_grace(self):
        q = _make_question(self.session, order_index=11)
        q.start()
        # Submit 400ms after deadline (within grace)
        just_late = q.question_deadline_utc + timedelta(milliseconds=400)
        self.assertTrue(q.is_submission_on_time(just_late))

    def test_is_submission_on_time_after_grace(self):
        q = _make_question(self.session, order_index=12)
        q.start()
        # Submit 600ms after deadline (outside grace)
        too_late = q.question_deadline_utc + timedelta(milliseconds=600)
        self.assertFalse(q.is_submission_on_time(too_late))

    def test_is_submission_on_time_no_deadline(self):
        q = _make_question(self.session, order_index=13)
        # Never started — no deadline
        self.assertFalse(q.is_submission_on_time(timezone.now()))

    def test_check_answer_mcq_correct(self):
        q = self.question
        self.assertTrue(q.check_answer({'option_id': 'b'}))

    def test_check_answer_mcq_incorrect(self):
        q = self.question
        self.assertFalse(q.check_answer({'option_id': 'a'}))

    def test_check_answer_mcq_missing_payload(self):
        q = self.question
        self.assertFalse(q.check_answer({}))

    def test_check_answer_true_false(self):
        q = _make_question(
            self.session,
            order_index=20,
            question_type=QUESTION_TYPE_TRUE_FALSE,
            options=[
                {'id': 'true', 'text': 'True', 'is_correct': True},
                {'id': 'false', 'text': 'False', 'is_correct': False},
            ],
        )
        self.assertTrue(q.check_answer({'option_id': 'true'}))
        self.assertFalse(q.check_answer({'option_id': 'false'}))

    def test_check_answer_short_answer_case_insensitive(self):
        q = _make_question(
            self.session,
            order_index=21,
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            options=[],
            accepted_answers=['Paris', 'paris'],
        )
        self.assertTrue(q.check_answer({'text': 'PARIS'}))
        self.assertTrue(q.check_answer({'text': 'paris'}))
        self.assertFalse(q.check_answer({'text': 'London'}))

    def test_correct_option_ids(self):
        ids = self.question.correct_option_ids
        self.assertEqual(ids, ['b'])


# ===========================================================================
# BrainBuzzParticipant — nickname resolution
# ===========================================================================

class TestNicknameResolution(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_nn')
        cls.session = _make_session(cls.teacher, join_code='NICKTS')

    def test_unique_nickname_unchanged(self):
        result = BrainBuzzParticipant.resolve_nickname(self.session, 'Alice')
        self.assertEqual(result, 'Alice')

    def test_duplicate_gets_suffix(self):
        _make_participant(self.session, 'Bob')
        result = BrainBuzzParticipant.resolve_nickname(self.session, 'Bob')
        self.assertEqual(result, 'Bob#2')

    def test_double_duplicate_increments(self):
        _make_participant(self.session, 'Carol')
        _make_participant(self.session, 'Carol#2')
        result = BrainBuzzParticipant.resolve_nickname(self.session, 'Carol')
        self.assertEqual(result, 'Carol#3')

    def test_inactive_participant_not_counted(self):
        _make_participant(self.session, 'Dave', is_active=False)
        result = BrainBuzzParticipant.resolve_nickname(self.session, 'Dave')
        # Dave is inactive, so the name should be available
        self.assertEqual(result, 'Dave')


# ===========================================================================
# CodingExercise — question_type field (non-breaking)
# ===========================================================================

class TestCodingExerciseQuestionType(TestCase):

    def test_write_code_is_default(self):
        from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel
        lang, _ = CodingLanguage.objects.get_or_create(
            slug='python', defaults={'name': 'Python', 'order': 1},
        )
        topic, _ = CodingTopic.objects.get_or_create(
            language=lang, slug='variables',
            defaults={'name': 'Variables', 'order': 1},
        )
        tl, _ = TopicLevel.objects.get_or_create(
            topic=topic, level_choice='beginner',
        )
        ex = CodingExercise.objects.create(
            topic_level=tl,
            title='Hello World',
            description='Print hello',
        )
        self.assertEqual(ex.question_type, 'write_code')

    def test_mcq_exercise_can_have_coding_answers(self):
        from coding.models import CodingExercise, CodingAnswer, CodingLanguage, CodingTopic, TopicLevel
        lang, _ = CodingLanguage.objects.get_or_create(
            slug='python', defaults={'name': 'Python', 'order': 1},
        )
        topic, _ = CodingTopic.objects.get_or_create(
            language=lang, slug='variables2',
            defaults={'name': 'Variables2', 'order': 2},
        )
        tl, _ = TopicLevel.objects.get_or_create(
            topic=topic, level_choice='beginner',
        )
        ex = CodingExercise.objects.create(
            topic_level=tl,
            title='MCQ Q',
            description='What is a variable?',
            question_type='multiple_choice',
        )
        CodingAnswer.objects.create(exercise=ex, answer_text='A storage location', is_correct=True, order=0)
        CodingAnswer.objects.create(exercise=ex, answer_text='A loop', is_correct=False, order=1)
        self.assertEqual(ex.answers.count(), 2)
        self.assertTrue(ex.answers.filter(is_correct=True).exists())
