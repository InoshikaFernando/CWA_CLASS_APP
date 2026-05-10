"""
test_read_window.py
~~~~~~~~~~~~~~~~~~~
Tests for the 10-second read window that hides answer tiles before the
per-question timer starts.

Server-side coverage:
  - question_deadline is extended by READ_WINDOW_SEC on 'start' and 'next'
  - read_window_sec appears in the state payload
  - submissions during the read window are rejected with HTTP 425
  - submissions after the read window succeed
  - time_taken_ms is measured from the start of the answer phase (not the
    start of the read window)
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    QUESTION_TYPE_MCQ,
)
from brainbuzz.views import READ_WINDOW_SEC

User = get_user_model()

_ANSWER_WINDOW_SEC = 20


def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type='application/json')


def _make_subject():
    return Subject.objects.get_or_create(slug='rw-maths', defaults={'name': 'RW Maths'})[0]


def _make_teacher(username='rw_teacher'):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@rw.test')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_session(teacher, code='RWTEST'):
    subject = _make_subject()
    session = BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY,
        time_per_question_sec=_ANSWER_WINDOW_SEC,
    )
    for i in range(2):
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order=i,
            question_text=f'RW Question {i}',
            question_type=QUESTION_TYPE_MCQ,
            options_json=[
                {'label': 'A', 'text': 'Correct', 'is_correct': True},
                {'label': 'B', 'text': 'Wrong',   'is_correct': False},
                {'label': 'C', 'text': 'Wrong',   'is_correct': False},
                {'label': 'D', 'text': 'Wrong',   'is_correct': False},
            ],
            time_limit_sec=_ANSWER_WINDOW_SEC,
            points_base=1000,
            source_model='RWTest',
            source_id=i,
        )
    return session


def _add_participant(session, nickname='Alice'):
    p = BrainBuzzParticipant.objects.create(session=session, nickname=nickname)
    return p


def _teacher_client(teacher):
    c = Client()
    c.force_login(teacher)
    return c


def _student_client(session, participant):
    c = Client()
    session_data = c.session
    session_data[f'bb_participant_{session.code}'] = participant.id
    session_data.save()
    return c


class TestReadWindowDeadline(TestCase):
    """Deadline is extended by READ_WINDOW_SEC on start and next."""

    def setUp(self):
        self.teacher = _make_teacher('rw_teacher_dl')
        self.session = _make_session(self.teacher, 'RWDL01')
        self.participant = _add_participant(self.session)
        self.tc = _teacher_client(self.teacher)

    def test_start_action_extends_deadline_by_read_window(self):
        action_url = reverse('brainbuzz:api_teacher_action', args=[self.session.code])
        t0 = timezone.now()
        with mock.patch('brainbuzz.views.timezone') as mock_tz:
            mock_tz.now.return_value = t0
            resp = _post_json(self.tc, action_url, {'action': 'start'})
        self.assertEqual(resp.status_code, 200)

        self.session.refresh_from_db()
        expected_deadline = t0 + timedelta(seconds=READ_WINDOW_SEC + _ANSWER_WINDOW_SEC)
        # Allow 1s tolerance for test timing
        diff = abs((self.session.question_deadline - expected_deadline).total_seconds())
        self.assertLess(diff, 1, f"Deadline off by {diff}s (expected read_window + answer_window)")

    def test_next_action_extends_deadline_by_read_window(self):
        # Put session in reveal state on question 0
        self.session.status = BrainBuzzSession.STATUS_REVEAL
        self.session.current_index = 0
        self.session.state_version = 1
        self.session.save()

        action_url = reverse('brainbuzz:api_teacher_action', args=[self.session.code])
        t0 = timezone.now()
        with mock.patch('brainbuzz.views.timezone') as mock_tz:
            mock_tz.now.return_value = t0
            resp = _post_json(self.tc, action_url, {'action': 'next', 'expected_current_index': 0})
        self.assertEqual(resp.status_code, 200)

        self.session.refresh_from_db()
        expected_deadline = t0 + timedelta(seconds=READ_WINDOW_SEC + _ANSWER_WINDOW_SEC)
        diff = abs((self.session.question_deadline - expected_deadline).total_seconds())
        self.assertLess(diff, 1, f"Deadline off by {diff}s on next action")


class TestReadWindowPayload(TestCase):
    """read_window_sec appears in state payload."""

    def setUp(self):
        self.teacher = _make_teacher('rw_teacher_pay')
        self.session = _make_session(self.teacher, 'RWPAY1')
        self.participant = _add_participant(self.session)
        # Activate session directly
        q0 = self.session.questions.get(order=0)
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.question_deadline = timezone.now() + timedelta(seconds=READ_WINDOW_SEC + _ANSWER_WINDOW_SEC)
        self.session.state_version = 1
        self.session.save()

    def test_state_payload_contains_read_window_sec(self):
        c = Client()
        state_url = reverse('brainbuzz:api_session_state', args=[self.session.code])
        resp = c.get(state_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('read_window_sec', data)
        self.assertEqual(data['read_window_sec'], READ_WINDOW_SEC)


class TestReadWindowSubmission(TestCase):
    """Submissions during read window are rejected; after read window succeed."""

    def setUp(self):
        self.teacher = _make_teacher('rw_teacher_sub')
        self.session = _make_session(self.teacher, 'RWSUB1')
        self.participant = _add_participant(self.session, 'Bob')

    def _activate_session(self, question_started_at):
        """Set session active with deadline = started_at + READ_WINDOW + ANSWER_WINDOW."""
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.question_deadline = question_started_at + timedelta(
            seconds=READ_WINDOW_SEC + _ANSWER_WINDOW_SEC
        )
        self.session.state_version = 1
        self.session.save()

    def _submit(self, at_time):
        c = Client()
        session_data = c.session
        session_data[f'bb_pid_{self.session.code}'] = self.participant.id
        session_data.save()
        submit_url = reverse('brainbuzz:api_submit', args=[self.session.code])
        payload = {
            'participant_id': self.participant.id,
            'question_index': 0,
            'answer_payload': {'option_label': 'A'},
        }
        with mock.patch('brainbuzz.views.timezone') as mock_tz:
            mock_tz.now.return_value = at_time
            return _post_json(c, submit_url, payload)

    def test_submit_during_read_window_returns_425(self):
        t0 = timezone.now()
        self._activate_session(t0)
        # Submit 3s into the 10s read window
        resp = self._submit(t0 + timedelta(seconds=3))
        self.assertEqual(resp.status_code, 425, resp.content)

    def test_submit_after_read_window_returns_200(self):
        t0 = timezone.now()
        self._activate_session(t0)
        # Submit 2s into the answer window (12s after activation)
        resp = self._submit(t0 + timedelta(seconds=READ_WINDOW_SEC + 2))
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_time_taken_ms_measured_from_answer_window_start(self):
        """time_taken_ms should be ~2000 when submitting 2s into answer window."""
        t0 = timezone.now()
        self._activate_session(t0)
        submit_time = t0 + timedelta(seconds=READ_WINDOW_SEC + 2)
        resp = self._submit(submit_time)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # time_taken_ms is capped to [0, answer_window_ms] and measured from
        # deadline - time_limit_sec = t0 + READ_WINDOW_SEC.
        # At submit_time: server_ms = (t0+12 - (t0+10)) * 1000 = 2000ms
        self.assertAlmostEqual(data['time_taken_ms'], 2000, delta=200)
