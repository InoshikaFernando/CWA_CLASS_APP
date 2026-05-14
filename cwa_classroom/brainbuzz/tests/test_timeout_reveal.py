"""
test_timeout_reveal.py
~~~~~~~~~~~~~~~~~~~~~~
Tests for CPP-267: correct answer visible on timeout, teacher controls pace.

Coverage:
  - During ACTIVE: student payload strips is_correct from options
  - During ACTIVE: teacher (is_host) always receives is_correct in options
  - During REVEAL: student payload includes is_correct and answer_distribution
  - During REVEAL: answer_distribution contains correct/incorrect vote counts
  - Server never auto-advances from REVEAL — only teacher action=next does
  - Teacher action=next from REVEAL advances to next question
  - Teacher action=next from ACTIVE (skip-reveal) also advances
  - Reveal payload includes correct_short_answer for teacher, not for anon student
"""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzAnswer,
    BrainBuzzParticipant,
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_SHORT_ANSWER,
)

User = get_user_model()

STATUS_ACTIVE = BrainBuzzSession.STATUS_ACTIVE
STATUS_REVEAL = BrainBuzzSession.STATUS_REVEAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@t.com')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_subject():
    return Subject.objects.get_or_create(slug='tr-maths', defaults={'name': 'TR Maths'})[0]


def _make_session(teacher, subject, status, code, current_index=0):
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=status,
        current_index=current_index,
        state_version=1,
        time_per_question_sec=20,
        question_deadline=timezone.now() + timedelta(seconds=60) if status == STATUS_ACTIVE else None,
    )


def _make_mcq_question(session, order=0, correct_label='A'):
    options = [
        {'label': 'A', 'text': 'Alpha', 'is_correct': correct_label == 'A'},
        {'label': 'B', 'text': 'Beta',  'is_correct': correct_label == 'B'},
        {'label': 'C', 'text': 'Gamma', 'is_correct': correct_label == 'C'},
    ]
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text='What is the correct answer?',
        question_type=QUESTION_TYPE_MCQ,
        options_json=options,
        time_limit_sec=20,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_short_question(session, order=0):
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text='What is 2 + 2?',
        question_type=QUESTION_TYPE_SHORT_ANSWER,
        options_json=[],
        correct_short_answer='4',
        time_limit_sec=20,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_participant(session, nickname='Tester'):
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _state_url(code):
    return reverse('brainbuzz:api_session_state', kwargs={'join_code': code})


def _action_url(code):
    return reverse('brainbuzz:api_teacher_action', kwargs={'join_code': code})


# ---------------------------------------------------------------------------
# is_correct visibility: student vs teacher in ACTIVE
# ---------------------------------------------------------------------------

class TestIsCorrectVisibility(TestCase):
    """Students must not see is_correct during ACTIVE; teachers always do."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('tr_vis_teacher')
        cls.subject = _make_subject()

    def setUp(self):
        self.session = _make_session(self.teacher, self.subject, STATUS_ACTIVE, 'TRVIS1')
        _make_mcq_question(self.session)

    def test_student_active_options_have_no_is_correct(self):
        """Anonymous student poll during ACTIVE must not expose is_correct."""
        resp = Client().get(_state_url(self.session.code))
        self.assertEqual(resp.status_code, 200)
        options = resp.json()['question']['options']
        for opt in options:
            self.assertNotIn('is_correct', opt)

    def test_teacher_active_options_include_is_correct(self):
        """Host poll during ACTIVE always includes is_correct (teacher sees the answer)."""
        c = Client()
        c.force_login(self.teacher)
        resp = c.get(_state_url(self.session.code))
        self.assertEqual(resp.status_code, 200)
        options = resp.json()['question']['options']
        is_correct_flags = [opt.get('is_correct') for opt in options]
        self.assertIn(True, is_correct_flags)

    def test_student_reveal_options_include_is_correct(self):
        """Student poll during REVEAL receives is_correct (correct answer now shown)."""
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRVIS2')
        _make_mcq_question(session)
        resp = Client().get(_state_url(session.code))
        self.assertEqual(resp.status_code, 200)
        options = resp.json()['question']['options']
        is_correct_flags = [opt.get('is_correct') for opt in options]
        self.assertIn(True, is_correct_flags)

    def test_student_reveal_exactly_one_correct_option(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRVIS3')
        _make_mcq_question(session, correct_label='B')
        resp = Client().get(_state_url(session.code))
        options = resp.json()['question']['options']
        correct = [o for o in options if o.get('is_correct')]
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]['label'], 'B')

    def test_correct_short_answer_hidden_from_student_during_active(self):
        session = _make_session(self.teacher, self.subject, STATUS_ACTIVE, 'TRVIS4')
        _make_short_question(session)
        resp = Client().get(_state_url(session.code))
        self.assertEqual(resp.json()['question']['correct_short_answer'], '')

    def test_correct_short_answer_visible_to_teacher_during_active(self):
        session = _make_session(self.teacher, self.subject, STATUS_ACTIVE, 'TRVIS5')
        _make_short_question(session)
        c = Client()
        c.force_login(self.teacher)
        resp = c.get(_state_url(session.code))
        self.assertEqual(resp.json()['question']['correct_short_answer'], '4')

    def test_correct_short_answer_visible_to_student_during_reveal(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRVIS6')
        _make_short_question(session)
        resp = Client().get(_state_url(session.code))
        self.assertEqual(resp.json()['question']['correct_short_answer'], '4')


# ---------------------------------------------------------------------------
# Answer distribution in REVEAL payload
# ---------------------------------------------------------------------------

class TestRevealDistribution(TestCase):
    """answer_distribution is populated during REVEAL and empty during ACTIVE."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('tr_dist_teacher')
        cls.subject = _make_subject()

    def test_distribution_empty_during_active(self):
        session = _make_session(self.teacher, self.subject, STATUS_ACTIVE, 'TRDST1')
        _make_mcq_question(session)
        resp = Client().get(_state_url(session.code))
        self.assertEqual(resp.json()['answer_distribution'], [])

    def test_distribution_present_during_reveal(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRDST2')
        _make_mcq_question(session)
        resp = Client().get(_state_url(session.code))
        dist = resp.json()['answer_distribution']
        self.assertIsInstance(dist, list)
        self.assertGreater(len(dist), 0)

    def test_distribution_includes_is_correct_flag(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRDST3')
        _make_mcq_question(session, correct_label='A')
        resp = Client().get(_state_url(session.code))
        dist = resp.json()['answer_distribution']
        correct_entries = [d for d in dist if d.get('is_correct')]
        self.assertEqual(len(correct_entries), 1)
        self.assertEqual(correct_entries[0]['label'], 'A')

    def test_distribution_counts_submitted_answers(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRDST4')
        sq = _make_mcq_question(session, correct_label='A')
        participant = _make_participant(session)
        BrainBuzzAnswer.objects.create(
            session_question=sq,
            participant=participant,
            selected_option_label='A',
            is_correct=True,
            points_awarded=500,
            time_taken_ms=3000,
        )
        resp = Client().get(_state_url(session.code))
        dist = resp.json()['answer_distribution']
        a_entry = next(d for d in dist if d['label'] == 'A')
        self.assertEqual(a_entry['count'], 1)


# ---------------------------------------------------------------------------
# Server never auto-advances from REVEAL
# ---------------------------------------------------------------------------

class TestServerNoAutoAdvance(TestCase):
    """Polling the state endpoint from REVEAL must not change the session status.
    Only teacher action=next advances the game."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('tr_noadv_teacher')
        cls.subject = _make_subject()

    def test_repeated_polls_from_reveal_stay_in_reveal(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRNAD1')
        _make_mcq_question(session)
        url = _state_url(session.code)
        c = Client()
        for _ in range(5):
            resp = c.get(url)
            self.assertEqual(resp.json()['status'], STATUS_REVEAL)
        session.refresh_from_db()
        self.assertEqual(session.status, STATUS_REVEAL)

    def test_state_version_unchanged_after_repeated_polls_from_reveal(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRNAD2')
        _make_mcq_question(session)
        original_version = session.state_version
        c = Client()
        for _ in range(3):
            c.get(_state_url(session.code))
        session.refresh_from_db()
        self.assertEqual(session.state_version, original_version)

    def test_teacher_next_from_reveal_advances_to_next_question(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRNAD3')
        _make_mcq_question(session, order=0)
        _make_mcq_question(session, order=1)
        c = Client()
        c.force_login(self.teacher)
        resp = c.post(
            _action_url(session.code),
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], STATUS_ACTIVE)
        self.assertEqual(data['current_index'], 1)

    def test_teacher_next_from_reveal_ends_game_when_no_more_questions(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRNAD4')
        _make_mcq_question(session, order=0)
        c = Client()
        c.force_login(self.teacher)
        resp = c.post(
            _action_url(session.code),
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], BrainBuzzSession.STATUS_FINISHED)

    def test_teacher_next_from_active_skips_reveal(self):
        """Teacher can force-advance directly from ACTIVE without waiting for auto-reveal."""
        session = _make_session(self.teacher, self.subject, STATUS_ACTIVE, 'TRNAD5')
        _make_mcq_question(session, order=0)
        _make_mcq_question(session, order=1)
        c = Client()
        c.force_login(self.teacher)
        resp = c.post(
            _action_url(session.code),
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], STATUS_ACTIVE)
        self.assertEqual(data['current_index'], 1)

    def test_unauthenticated_cannot_call_next(self):
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRNAD6')
        _make_mcq_question(session)
        resp = Client().post(
            _action_url(session.code),
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        # Must not advance — redirect to login or 403
        self.assertIn(resp.status_code, [302, 403])
        session.refresh_from_db()
        self.assertEqual(session.status, STATUS_REVEAL)

    def test_wrong_expected_index_is_noop(self):
        """Stale client sending wrong expected_index must not advance the session."""
        session = _make_session(self.teacher, self.subject, STATUS_REVEAL, 'TRNAD7')
        _make_mcq_question(session, order=0)
        _make_mcq_question(session, order=1)
        c = Client()
        c.force_login(self.teacher)
        resp = c.post(
            _action_url(session.code),
            data=json.dumps({'action': 'next', 'expected_current_index': 99}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.current_index, 0)
