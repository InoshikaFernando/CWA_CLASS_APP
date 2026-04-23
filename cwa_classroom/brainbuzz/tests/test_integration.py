"""
Integration tests for BrainBuzz.

Covers:
  - Full 10-question session with 30 simulated students
  - Varying speeds and correctness → verifies leaderboard is correct
  - CSV export schema and content validation
"""
import csv
import io
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzSubmission,
    calculate_brainbuzz_score,
    QUESTION_TYPE_MULTIPLE_CHOICE,
)

User = get_user_model()


def _post_json(client, url, payload):
    return client.post(
        url, data=json.dumps(payload), content_type='application/json',
    )


def _make_teacher():
    u = User.objects.create_user(
        username='integ_teacher', password='pass', email='integ_teacher@test.com',
    )
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _build_session_with_questions(teacher, num_questions=10):
    """Build an in-progress BrainBuzz session with `num_questions` MCQ questions."""
    session = BrainBuzzSession.objects.create(
        join_code='INTEG1',
        created_by=teacher,
        subject=BrainBuzzSession.SUBJECT_MATHS,
        state=BrainBuzzSession.LOBBY,
    )
    for i in range(num_questions):
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order_index=i,
            question_text=f'Integration Question {i + 1}',
            question_type=QUESTION_TYPE_MULTIPLE_CHOICE,
            options=[
                {'id': 'correct', 'text': 'Correct Answer', 'is_correct': True},
                {'id': 'wrong1',  'text': 'Wrong A',        'is_correct': False},
                {'id': 'wrong2',  'text': 'Wrong B',        'is_correct': False},
                {'id': 'wrong3',  'text': 'Wrong C',        'is_correct': False},
            ],
            time_limit_seconds=20,
        )
    return session


def _join_30_students(session):
    """Create 30 participant records directly (bypasses HTTP for speed)."""
    participants = []
    for i in range(30):
        p = BrainBuzzParticipant.objects.create(
            session=session,
            nickname=f'Student{i + 1:02d}',
        )
        participants.append(p)
    return participants


def _simulate_question(session, question, participants, correct_fraction=0.8):
    """Simulate all participants answering question with varying speeds.

    correct_fraction: fraction of participants who answer correctly.
    """
    question.start()
    # Simulate answers arriving at varying times during the window
    num_correct = int(len(participants) * correct_fraction)
    for idx, participant in enumerate(participants):
        is_correct = idx < num_correct
        option_id = 'correct' if is_correct else 'wrong1'

        # Simulate seconds remaining proportional to position (early → more points)
        seconds_into_window = (idx / len(participants)) * question.time_limit_seconds
        seconds_remaining = max(0.1, question.time_limit_seconds - seconds_into_window)

        score = calculate_brainbuzz_score(question.time_limit_seconds, seconds_remaining) if is_correct else 0

        BrainBuzzSubmission.objects.create(
            participant=participant,
            session_question=question,
            answer_payload={'option_id': option_id},
            is_correct=is_correct,
            score_awarded=score,
        )
        if score > 0:
            participant.total_score += score
            participant.save(update_fields=['total_score'])


# ===========================================================================
# Full 10-question session with 30 students
# ===========================================================================

class TestFullSession30Students(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()

    def test_full_session_correct_leaderboard(self):
        """Simulate 30 students through 10 questions; verify leaderboard."""
        NUM_QUESTIONS = 10
        NUM_STUDENTS = 30

        session = _build_session_with_questions(self.teacher, NUM_QUESTIONS)
        participants = _join_30_students(session)
        self.assertEqual(len(participants), NUM_STUDENTS)

        # Start session
        session.state = BrainBuzzSession.IN_PROGRESS
        session.current_question_index = 0
        session.bump_version()

        # Play each question
        questions = list(session.questions.order_by('order_index'))
        for q in questions:
            _simulate_question(session, q, participants, correct_fraction=0.8)

        # End session
        session.state = BrainBuzzSession.ENDED
        session.current_question_index = None
        session.bump_version()

        # Verify leaderboard ordering
        leaderboard = list(session.leaderboard())
        self.assertEqual(len(leaderboard), NUM_STUDENTS)

        # Leaderboard must be sorted by total_score desc
        for i in range(len(leaderboard) - 1):
            self.assertGreaterEqual(
                leaderboard[i].total_score,
                leaderboard[i + 1].total_score,
                msg=f"Rank {i+1} score {leaderboard[i].total_score} < rank {i+2} score {leaderboard[i+1].total_score}",
            )

        # The first 24 students (80% × 30) got correct answers every round → should have higher scores
        correct_total = sum(p.total_score for p in participants[:24])
        wrong_total   = sum(p.total_score for p in participants[24:])
        self.assertGreater(correct_total, wrong_total)

    def test_total_submissions_match(self):
        """30 students × 10 questions = exactly 300 submissions."""
        session = _build_session_with_questions(self.teacher, 10)
        session.join_code = 'INTEG2'
        session.save(update_fields=['join_code'])
        participants = _join_30_students(session)
        session.state = BrainBuzzSession.IN_PROGRESS
        session.save(update_fields=['state'])

        for q in session.questions.order_by('order_index'):
            _simulate_question(session, q, participants)

        total = BrainBuzzSubmission.objects.filter(
            participant__session=session,
        ).count()
        self.assertEqual(total, 300)

    def test_scoring_range_in_bounds(self):
        """All score_awarded values must be 0 or in [500, 1000]."""
        session = _build_session_with_questions(self.teacher, 3)
        session.join_code = 'INTEG3'
        session.save(update_fields=['join_code'])
        participants = _join_30_students(session)
        session.state = BrainBuzzSession.IN_PROGRESS
        session.save(update_fields=['state'])

        for q in session.questions.order_by('order_index'):
            _simulate_question(session, q, participants)

        subs = BrainBuzzSubmission.objects.filter(participant__session=session)
        for sub in subs:
            if sub.is_correct:
                self.assertGreaterEqual(sub.score_awarded, 500)
                self.assertLessEqual(sub.score_awarded, 1000)
            else:
                self.assertEqual(sub.score_awarded, 0)


# ===========================================================================
# CSV export validation
# ===========================================================================

class TestCsvExport(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()

    def test_csv_schema_and_content(self):
        """CSV must have correct headers and one row per participant."""
        session = _build_session_with_questions(self.teacher, 5)
        session.join_code = 'CSVTST'
        session.state = BrainBuzzSession.ENDED
        session.save(update_fields=['join_code', 'state'])

        participants = []
        for i, name in enumerate(['Alice', 'Bob', 'Carol']):
            p = BrainBuzzParticipant.objects.create(
                session=session,
                nickname=name,
                total_score=(3 - i) * 500,
            )
            participants.append(p)

        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:export_csv', kwargs={'join_code': 'CSVTST'})
        res = c.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'text/csv')
        self.assertIn('attachment', res.get('Content-Disposition', ''))
        self.assertIn('CSVTST', res.get('Content-Disposition', ''))

        content = res.content.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)

        # Header row
        header = rows[0]
        self.assertEqual(header[0], 'Rank')
        self.assertEqual(header[1], 'Nickname')
        self.assertEqual(header[3], 'Total Score')

        # Data rows — one per participant
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), 3)

        # First data row should be Alice (highest score = 1500)
        self.assertEqual(data_rows[0][1], 'Alice')
        self.assertEqual(data_rows[0][3], '1500')

        # Ranks must be sequential
        for i, row in enumerate(data_rows):
            self.assertEqual(row[0], str(i + 1))

    def test_csv_404_for_wrong_teacher(self):
        """Only the session creator can export."""
        other = User.objects.create_user(
            username='other_teacher', password='pass', email='other@test.com',
        )
        role, _ = Role.objects.get_or_create(name=Role.TEACHER)
        other.roles.add(role)

        session = _build_session_with_questions(self.teacher, 2)
        session.join_code = 'CSVOTH'
        session.state = BrainBuzzSession.ENDED
        session.save(update_fields=['join_code', 'state'])

        c = Client()
        c.force_login(other)
        url = reverse('brainbuzz:export_csv', kwargs={'join_code': 'CSVOTH'})
        res = c.get(url)
        self.assertEqual(res.status_code, 404)


# ===========================================================================
# API polling — versioned state
# ===========================================================================

class TestVersionedPolling(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()

    def test_state_version_increments_on_each_action(self):
        session = _build_session_with_questions(self.teacher, 3)
        session.join_code = 'POLLV1'
        session.save(update_fields=['join_code'])

        c = Client()
        c.force_login(self.teacher)

        action_url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'POLLV1'})
        state_url  = reverse('brainbuzz:api_session_state',  kwargs={'join_code': 'POLLV1'})

        # Initial version
        res = c.get(state_url)
        v0 = res.json()['state_version']

        # Start
        _post_json(c, action_url, {'action': 'start', 'expected_current_index': None})
        res = c.get(state_url)
        v1 = res.json()['state_version']
        self.assertEqual(v1, v0 + 1)

        # Next
        _post_json(c, action_url, {'action': 'next', 'expected_current_index': 0})
        res = c.get(state_url)
        v2 = res.json()['state_version']
        self.assertEqual(v2, v1 + 1)

    def test_304_returned_between_state_changes(self):
        session = _build_session_with_questions(self.teacher, 2)
        session.join_code = 'POLL04'
        session.save(update_fields=['join_code'])

        c = Client()
        state_url = reverse('brainbuzz:api_session_state', kwargs={'join_code': 'POLL04'})

        res = c.get(state_url)
        version = res.json()['state_version']

        # Poll again with same version — should be 304
        res2 = c.get(f'{state_url}?since={version}')
        self.assertEqual(res2.status_code, 304)
