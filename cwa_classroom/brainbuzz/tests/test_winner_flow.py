"""
End-to-end winner verification for a 2-student BrainBuzz session.

Flow exercised over real HTTP:
  - 1 teacher account, 2 student accounts (3 accounts)
  - Teacher creates a session (via ORM helper for question setup)
  - Both students join via /api/join/
  - Teacher starts the session via /api/session/<code>/action/
  - Alice answers correctly, Bob answers wrong
  - Teacher advances and ends the session
  - Leaderboard API confirms Alice is the winner
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    QUESTION_TYPE_MCQ,
)

User = get_user_model()

NUM_QUESTIONS = 3
TIME_PER_Q = 20


def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type='application/json')


def _make_user(username, role_name=None):
    user = User.objects.create_user(
        username=username,
        password='pass',
        email=f'{username}@test.com',
    )
    if role_name:
        role, _ = Role.objects.get_or_create(name=role_name)
        user.roles.add(role)
    return user


def _build_session(teacher, code='WINNER1'):
    subject, _ = Subject.objects.get_or_create(
        slug='winner-flow-maths', defaults={'name': 'Winner Flow Maths'},
    )
    session = BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY,
        time_per_question_sec=TIME_PER_Q,
    )
    for i in range(NUM_QUESTIONS):
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order=i,
            question_text=f'Q{i + 1}: pick A',
            question_type=QUESTION_TYPE_MCQ,
            options_json=[
                {'label': 'A', 'text': 'Right',  'is_correct': True},
                {'label': 'B', 'text': 'Wrong1', 'is_correct': False},
                {'label': 'C', 'text': 'Wrong2', 'is_correct': False},
                {'label': 'D', 'text': 'Wrong3', 'is_correct': False},
            ],
            source_model='WinnerFlowTest',
            source_id=i,
        )
    return session


class TestTwoStudentWinner(TestCase):
    """Teacher + 2 students, deterministic winner via real HTTP endpoints."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_user('flow_teacher', Role.TEACHER)
        cls.student1 = _make_user('flow_alice', Role.STUDENT)
        cls.student2 = _make_user('flow_bob', Role.STUDENT)

    @mock.patch('brainbuzz.views._check_join_rate_limit', return_value=True)
    def test_alice_wins_with_correct_answers(self, _rate_limit):
        # ── Build session as the teacher ─────────────────────────────────
        session = _build_session(self.teacher)
        join_code = session.code

        # ── Each student needs its own Client (separate Django session) ──
        alice = Client()
        bob = Client()

        # ── Both students join ──────────────────────────────────────────
        for client, nick in ((alice, 'Alice'), (bob, 'Bob')):
            r = _post_json(client, reverse('brainbuzz:api_join'), {
                'code': join_code, 'nickname': nick,
            })
            self.assertEqual(r.status_code, 200, r.content)
            self.assertIn('participant_id', r.json())

        self.assertEqual(session.participants.count(), 2)

        # ── Teacher logs in and starts session ───────────────────────────
        teacher_client = Client()
        teacher_client.force_login(self.teacher)

        action_url = reverse('brainbuzz:api_teacher_action', args=[join_code])
        submit_url = reverse('brainbuzz:api_submit',         args=[join_code])

        r = _post_json(teacher_client, action_url, {'action': 'start'})
        self.assertEqual(r.status_code, 200, r.content)

        # ── Play through every question ──────────────────────────────────
        for q_index in range(NUM_QUESTIONS):
            # Alice answers correctly (A); Bob answers wrong (B)
            r1 = _post_json(alice, submit_url, {
                'question_index': q_index,
                'answer_payload': {'option_label': 'A'},
            })
            self.assertEqual(r1.status_code, 200, r1.content)
            self.assertTrue(r1.json()['is_correct'])

            r2 = _post_json(bob, submit_url, {
                'question_index': q_index,
                'answer_payload': {'option_label': 'B'},
            })
            self.assertEqual(r2.status_code, 200, r2.content)
            self.assertFalse(r2.json()['is_correct'])

            # Teacher advances (last 'next' transitions to FINISHED)
            r = _post_json(teacher_client, action_url, {
                'action': 'next', 'expected_current_index': q_index,
            })
            self.assertEqual(r.status_code, 200, r.content)

        # ── Session must now be FINISHED ─────────────────────────────────
        session.refresh_from_db()
        self.assertEqual(session.status, BrainBuzzSession.STATUS_FINISHED)

        # ── Leaderboard API confirms the winner ──────────────────────────
        leaderboard_url = reverse('brainbuzz:api_leaderboard', args=[join_code])
        r = teacher_client.get(leaderboard_url)
        self.assertEqual(r.status_code, 200, r.content)

        rows = r.json().get('leaderboard') or r.json().get('participants') or []
        self.assertEqual(len(rows), 2, f'Unexpected leaderboard payload: {r.json()}')

        winner = rows[0]
        self.assertEqual(winner['nickname'], 'Alice')
        self.assertGreater(winner['score'], rows[1]['score'])
        self.assertEqual(rows[1]['nickname'], 'Bob')
        self.assertEqual(rows[1]['score'], 0)
