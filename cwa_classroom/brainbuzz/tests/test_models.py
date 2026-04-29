"""
Unit tests for brainbuzz models.

Covers:
  - generate_join_code: length, alphabet, uniqueness, collision handling
  - calculate_brainbuzz_score: correct ranges, edge cases
  - BrainBuzzSession: creation, __str__, status constants
  - BrainBuzzSessionQuestion: options_json format, correct_short_answer
  - BrainBuzzParticipant: score, unique nickname constraint
  - BrainBuzzAnswer: is_correct, points_awarded
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzAnswer,
    generate_join_code,
    calculate_brainbuzz_score,
    _JOIN_CODE_ALPHABET,
    _JOIN_CODE_LENGTH,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
)

STATUS_LOBBY = BrainBuzzSession.STATUS_LOBBY
STATUS_ACTIVE = BrainBuzzSession.STATUS_ACTIVE
STATUS_FINISHED = BrainBuzzSession.STATUS_FINISHED

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subject(**kwargs):
    defaults = {'name': 'Maths', 'slug': 'maths'}
    defaults.update(kwargs)
    return Subject.objects.get_or_create(slug=defaults['slug'], defaults=defaults)[0]


def _make_teacher(**kwargs):
    defaults = {'username': 'teacher1', 'password': 'pass', 'email': 'teacher@test.com'}
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_session(teacher, subject, **kwargs):
    defaults = {
        'code': 'ABC123',
        'host': teacher,
        'subject': subject,
        'status': STATUS_LOBBY,
    }
    defaults.update(kwargs)
    return BrainBuzzSession.objects.create(**defaults)


def _make_question(session, order=0, **kwargs):
    defaults = {
        'session': session,
        'order': order,
        'question_text': 'What is 2 + 2?',
        'question_type': QUESTION_TYPE_MCQ,
        'options_json': [
            {'label': 'A', 'text': '3', 'is_correct': False},
            {'label': 'B', 'text': '4', 'is_correct': True},
            {'label': 'C', 'text': '5', 'is_correct': False},
            {'label': 'D', 'text': '6', 'is_correct': False},
        ],
        'source_model': 'TestQuestion',
        'source_id': 1,
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
        cls.subject = _make_subject()

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
        BrainBuzzSession.objects.create(
            code='AAAAAA', host=self.teacher, subject=self.subject, status=STATUS_LOBBY,
        )
        with patch('brainbuzz.models.secrets.choice') as mock_choice:
            mock_choice.side_effect = list('AAAAAA') + list('BBBBBB')
            code = generate_join_code()
            self.assertEqual(code, 'BBBBBB')

    def test_raises_after_max_retries(self):
        codes = ['ZZZZZZ'] + [f'Z{str(i).zfill(5)}' for i in range(9)]
        for c in codes:
            BrainBuzzSession.objects.create(
                code=c, host=self.teacher, subject=self.subject, status=STATUS_LOBBY,
            )
        with patch('brainbuzz.models.secrets.choice') as mock_choice:
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
        cls.teacher = _make_teacher(username='teacher_sess')
        cls.subject = _make_subject(slug='maths-sess')
        cls.session = _make_session(cls.teacher, cls.subject)

    def test_str_representation(self):
        s = str(self.session)
        self.assertIn('BrainBuzz', s)
        self.assertIn(self.session.code, s)
        self.assertIn(self.session.host.username, s)

    def test_status_constants_exist(self):
        self.assertEqual(BrainBuzzSession.STATUS_LOBBY, STATUS_LOBBY)
        self.assertEqual(BrainBuzzSession.STATUS_ACTIVE, STATUS_ACTIVE)
        self.assertEqual(BrainBuzzSession.STATUS_FINISHED, STATUS_FINISHED)

    def test_default_status_is_lobby(self):
        self.assertEqual(self.session.status, STATUS_LOBBY)

    def test_state_version_starts_at_zero(self):
        self.assertEqual(self.session.state_version, 0)

    def test_state_version_manual_increment(self):
        s = _make_session(self.teacher, self.subject, code='VERSN1')
        BrainBuzzSession.objects.filter(pk=s.pk).update(state_version=s.state_version + 1)
        s.refresh_from_db()
        self.assertEqual(s.state_version, 1)

    def test_current_index_default_zero(self):
        self.assertEqual(self.session.current_index, 0)

    def test_ordered_by_created_at_desc(self):
        s1 = _make_session(self.teacher, self.subject, code='ORDR11')
        s2 = _make_session(self.teacher, self.subject, code='ORDR22')
        sessions = list(BrainBuzzSession.objects.filter(
            code__in=['ORDR11', 'ORDR22']
        ))
        self.assertEqual(sessions[0].code, 'ORDR22')

    def test_status_transition(self):
        s = _make_session(self.teacher, self.subject, code='TRNST1')
        s.status = STATUS_ACTIVE
        s.save(update_fields=['status'])
        s.refresh_from_db()
        self.assertEqual(s.status, STATUS_ACTIVE)


# ===========================================================================
# BrainBuzzSessionQuestion
# ===========================================================================

class TestBrainBuzzSessionQuestion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_sq')
        cls.subject = _make_subject(slug='maths-sq')
        cls.session = _make_session(cls.teacher, cls.subject, code='SQTEST')

    def test_question_creation(self):
        q = _make_question(self.session, order=0)
        self.assertEqual(q.question_text, 'What is 2 + 2?')
        self.assertEqual(q.question_type, QUESTION_TYPE_MCQ)

    def test_options_json_format(self):
        q = _make_question(self.session, order=1)
        self.assertEqual(len(q.options_json), 4)
        labels = [o['label'] for o in q.options_json]
        self.assertEqual(labels, ['A', 'B', 'C', 'D'])

    def test_correct_option_in_options_json(self):
        q = _make_question(self.session, order=2)
        correct = [o for o in q.options_json if o['is_correct']]
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]['label'], 'B')

    def test_short_answer_question(self):
        q = _make_question(
            self.session,
            order=3,
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            options_json=[],
            correct_short_answer='Paris',
        )
        self.assertEqual(q.correct_short_answer, 'Paris')
        self.assertEqual(q.options_json, [])

    def test_str_contains_order_and_code(self):
        q = _make_question(self.session, order=4)
        s = str(q)
        self.assertIn('Q4', s)
        self.assertIn(self.session.code, s)

    def test_unique_order_per_session(self):
        from django.db import IntegrityError
        _make_question(self.session, order=99)
        with self.assertRaises(Exception):
            _make_question(self.session, order=99)

    def test_compat_alias_question_type(self):
        self.assertEqual(QUESTION_TYPE_MULTIPLE_CHOICE, QUESTION_TYPE_MCQ)


# ===========================================================================
# BrainBuzzParticipant
# ===========================================================================

class TestBrainBuzzParticipant(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_part')
        cls.subject = _make_subject(slug='maths-part')
        cls.session = _make_session(cls.teacher, cls.subject, code='PARTST')

    def test_participant_default_score(self):
        p = _make_participant(self.session, 'Alice')
        self.assertEqual(p.score, 0)

    def test_participant_score_update(self):
        p = _make_participant(self.session, 'Bob')
        p.score = 750
        p.save(update_fields=['score'])
        p.refresh_from_db()
        self.assertEqual(p.score, 750)

    def test_unique_nickname_per_session(self):
        _make_participant(self.session, 'Carol')
        with self.assertRaises(Exception):
            _make_participant(self.session, 'Carol')

    def test_same_nickname_different_sessions(self):
        s2 = _make_session(self.teacher, self.subject, code='PART2S')
        p1 = _make_participant(self.session, 'Dave')
        p2 = _make_participant(s2, 'Dave')
        self.assertEqual(p1.nickname, p2.nickname)

    def test_ordering_by_score_desc(self):
        s = _make_session(self.teacher, self.subject, code='ORDRPT')
        _make_participant(s, 'Low', score=100)
        _make_participant(s, 'High', score=900)
        _make_participant(s, 'Mid', score=500)
        participants = list(s.participants.all())
        self.assertEqual(participants[0].nickname, 'High')
        self.assertEqual(participants[2].nickname, 'Low')

    def test_str_contains_nickname_and_score(self):
        p = _make_participant(self.session, 'Eve')
        s = str(p)
        self.assertIn('Eve', s)
        self.assertIn(self.session.code, s)


# ===========================================================================
# BrainBuzzAnswer
# ===========================================================================

class TestBrainBuzzAnswer(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_ans')
        cls.subject = _make_subject(slug='maths-ans')
        cls.session = _make_session(cls.teacher, cls.subject, code='ANSTST')
        cls.question = _make_question(cls.session, order=0)
        cls.participant = _make_participant(cls.session, 'Fiona')

    def test_answer_creation(self):
        a = BrainBuzzAnswer.objects.create(
            participant=self.participant,
            session_question=self.question,
            selected_option_label='B',
            time_taken_ms=5000,
            points_awarded=800,
            is_correct=True,
        )
        self.assertTrue(a.is_correct)
        self.assertEqual(a.points_awarded, 800)

    def test_wrong_answer(self):
        a = BrainBuzzAnswer.objects.create(
            participant=self.participant,
            session_question=self.question,
            selected_option_label='A',
            time_taken_ms=8000,
            points_awarded=0,
            is_correct=False,
        )
        self.assertFalse(a.is_correct)
        self.assertEqual(a.points_awarded, 0)

    def test_unique_answer_per_participant_question(self):
        BrainBuzzAnswer.objects.create(
            participant=self.participant,
            session_question=self.question,
            selected_option_label='C',
            time_taken_ms=3000,
            points_awarded=500,
            is_correct=False,
        )
        with self.assertRaises(Exception):
            BrainBuzzAnswer.objects.create(
                participant=self.participant,
                session_question=self.question,
                selected_option_label='B',
                time_taken_ms=4000,
                points_awarded=800,
                is_correct=True,
            )

    def test_str_contains_nickname_and_result(self):
        q2 = _make_question(self.session, order=50, source_id=50)
        a = BrainBuzzAnswer.objects.create(
            participant=self.participant,
            session_question=q2,
            selected_option_label='B',
            time_taken_ms=2000,
            points_awarded=900,
            is_correct=True,
        )
        s = str(a)
        self.assertIn('Fiona', s)


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
