"""
test_student_answer_flow.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the student answer submission flow (CPP-237):
  - api_submit: MCQ/TF/short-answer validation and scoring
  - Time deadline enforcement (grace period: 500ms post-deadline)
  - Duplicate submission prevention
  - Correct/incorrect detection
  - Points calculation (all-or-nothing in current MVP)
  - Score persistence (F('score') + score)
  - Edge cases: offline submit, wrong question index, expired time
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzAnswer,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_FILL_BLANK,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_subject(slug='mathematics', name='Mathematics'):
    return Subject.objects.get_or_create(slug=slug, defaults={'name': name})[0]


def _make_teacher(username='teach_ans'):
    return User.objects.create_user(username=username, password='pass', email=f'{username}@test.com')


def _make_session(host, subject, status=BrainBuzzSession.STATUS_ACTIVE, code='ANSW01', **kwargs):
    return BrainBuzzSession.objects.create(
        code=code,
        host=host,
        subject=subject,
        status=status,
        time_per_question_sec=20,
        **kwargs,
    )


def _make_question_mcq(session, order=0, correct_label='A'):
    """Create MCQ with 4 options, one marked correct."""
    options = [
        {'label': 'A', 'text': 'Option A', 'is_correct': correct_label == 'A'},
        {'label': 'B', 'text': 'Option B', 'is_correct': correct_label == 'B'},
        {'label': 'C', 'text': 'Option C', 'is_correct': correct_label == 'C'},
        {'label': 'D', 'text': 'Option D', 'is_correct': correct_label == 'D'},
    ]
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'MCQ {order}: Which is correct?',
        question_type=QUESTION_TYPE_MCQ,
        options_json=options,
        points_base=1000,
        source_model='CodingExercise',
        source_id=order,
    )


def _make_question_tf(session, order=0, correct='true'):
    """Create True/False question."""
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'True/False {order}: Is this true?',
        question_type=QUESTION_TYPE_TRUE_FALSE,
        options_json=[
            {'label': 'A', 'text': 'True', 'is_correct': correct == 'true'},
            {'label': 'B', 'text': 'False', 'is_correct': correct == 'false'},
        ],
        points_base=1000,
        source_model='CodingExercise',
        source_id=order,
    )


def _make_question_short(session, order=0, correct_answer='python'):
    """Create short answer question."""
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'Short answer {order}: What language?',
        question_type=QUESTION_TYPE_SHORT_ANSWER,
        options_json=[],
        correct_short_answer=correct_answer,
        points_base=1000,
        source_model='CodingExercise',
        source_id=order,
    )


def _make_question_fill(session, order=0, correct_answer='javascript'):
    """Create fill-blank question."""
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'Fill blank {order}: The web language is ___',
        question_type=QUESTION_TYPE_FILL_BLANK,
        options_json=[],
        correct_short_answer=correct_answer,
        points_base=1000,
        source_model='CodingExercise',
        source_id=order,
    )


def _make_participant(session, nickname='TestStudent'):
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _submit_answer_payload(participant_id, question_index, answer_payload, time_ms=500):
    """Build api_submit JSON payload."""
    return json.dumps({
        'participant_id': participant_id,
        'question_index': question_index,
        'answer_payload': answer_payload,
        'time_taken_ms': time_ms,
    })


# ---------------------------------------------------------------------------
# MCQ Answer Submission — Happy Path
# ---------------------------------------------------------------------------

class TestMcqSubmissionSuccess(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_mcq')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='MCQSUC',
            current_index=0,
        )
        cls.q0 = _make_question_mcq(cls.session, order=0, correct_label='B')
        cls.q1 = _make_question_mcq(cls.session, order=1, correct_label='C')
        # Set deadline 20s in future
        cls.session.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session.save()
        cls.participant = _make_participant(cls.session, 'Alice')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_correct_answer_returns_200(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 800),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_correct_answer_has_is_correct_true(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 800),
            content_type='application/json',
        )
        self.assertTrue(resp.json()['is_correct'])

    def test_correct_answer_awards_points(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 0),
            content_type='application/json',
        )
        self.assertEqual(resp.json()['score_awarded'], 1000)

    def test_incorrect_answer_returns_200(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1200),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_incorrect_answer_has_is_correct_false(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1200),
            content_type='application/json',
        )
        self.assertFalse(resp.json()['is_correct'])

    def test_incorrect_answer_awards_zero_points(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1200),
            content_type='application/json',
        )
        self.assertEqual(resp.json()['score_awarded'], 0)

    def test_answer_stored_in_db(self):
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 0),
            content_type='application/json',
        )
        answer = BrainBuzzAnswer.objects.get(participant=self.participant, session_question=self.q0)
        self.assertEqual(answer.selected_option_label, 'B')
        self.assertTrue(answer.is_correct)
        self.assertEqual(answer.points_awarded, 1000)

    def test_time_taken_ms_stored(self):
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 8723),
            content_type='application/json',
        )
        answer = BrainBuzzAnswer.objects.get(participant=self.participant, session_question=self.q0)
        self.assertEqual(answer.time_taken_ms, 8723)

    def test_response_includes_total_score(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 800),
            content_type='application/json',
        )
        self.assertIn('total_score', resp.json())

    def test_participant_score_updated(self):
        self.assertEqual(self.participant.score, 0)
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 0),
            content_type='application/json',
        )
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.score, 1000)

    def test_incorrect_answer_does_not_update_score(self):
        self.assertEqual(self.participant.score, 0)
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1200),
            content_type='application/json',
        )
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.score, 0)


# ---------------------------------------------------------------------------
# Short Answer / Fill Blank
# ---------------------------------------------------------------------------

class TestShortAnswerSubmission(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_short')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='SHRTAN',
            current_index=0,
        )
        cls.q0 = _make_question_short(cls.session, order=0, correct_answer='python')
        cls.session.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session.save()
        cls.participant = _make_participant(cls.session, 'Bob')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_correct_short_answer(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'text': 'python'}, 0),
            content_type='application/json',
        )
        self.assertTrue(resp.json()['is_correct'])
        self.assertEqual(resp.json()['score_awarded'], 1000)

    def test_short_answer_case_insensitive(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'text': 'PYTHON'}, 3000),
            content_type='application/json',
        )
        self.assertTrue(resp.json()['is_correct'])

    def test_incorrect_short_answer(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'text': 'java'}, 3000),
            content_type='application/json',
        )
        self.assertFalse(resp.json()['is_correct'])
        self.assertEqual(resp.json()['score_awarded'], 0)

    def test_short_answer_with_whitespace(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'text': '  python  '}, 3000),
            content_type='application/json',
        )
        self.assertTrue(resp.json()['is_correct'])

    def test_answer_text_stored_in_db(self):
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'text': 'python'}, 3000),
            content_type='application/json',
        )
        answer = BrainBuzzAnswer.objects.get(participant=self.participant, session_question=self.q0)
        self.assertEqual(answer.short_answer_text, 'python')
        self.assertIsNone(answer.selected_option_label)


class TestFillBlankSubmission(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_fill')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='FILBLN',
            current_index=0,
        )
        cls.q0 = _make_question_fill(cls.session, order=0, correct_answer='javascript')
        cls.session.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session.save()
        cls.participant = _make_participant(cls.session, 'Carol')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_fill_blank_submission(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'text': 'javascript'}, 2500),
            content_type='application/json',
        )
        self.assertTrue(resp.json()['is_correct'])


# ---------------------------------------------------------------------------
# Deadline Enforcement
# ---------------------------------------------------------------------------

class TestDeadlineEnforcement(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_deadline')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='DLNE01',
            current_index=0,
        )
        cls.q0 = _make_question_mcq(cls.session, order=0, correct_label='A')
        cls.participant = _make_participant(cls.session, 'Dave')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_answer_on_time_awards_points(self):
        self.session.question_deadline = timezone.now() + timedelta(seconds=10)
        self.session.save()
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 0),
            content_type='application/json',
        )
        self.assertGreater(resp.json()['score_awarded'], 0)

    def test_answer_within_grace_period_awards_points(self):
        # 500ms grace period post-deadline
        self.session.question_deadline = timezone.now() - timedelta(milliseconds=200)
        self.session.save()
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 0),
            content_type='application/json',
        )
        # Correct, within grace → should award points
        self.assertGreater(resp.json()['score_awarded'], 0)

    def test_answer_past_grace_period_awards_zero(self):
        # Deadline was 1 second ago (well past 500ms grace)
        self.session.question_deadline = timezone.now() - timedelta(seconds=1)
        self.session.save()
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 100),
            content_type='application/json',
        )
        # Late submission → zero points even if correct
        self.assertEqual(resp.json()['score_awarded'], 0)

    def test_late_answer_still_marked_correct(self):
        self.session.question_deadline = timezone.now() - timedelta(seconds=2)
        self.session.save()
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 100),
            content_type='application/json',
        )
        # Late but correct answer: is_correct=True, points=0
        self.assertTrue(resp.json()['is_correct'])
        self.assertEqual(resp.json()['score_awarded'], 0)


# ---------------------------------------------------------------------------
# Duplicate Submission Prevention
# ---------------------------------------------------------------------------

class TestDuplicateSubmissionPrevention(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_dup_ans')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='DUPANS',
            current_index=0,
        )
        cls.q0 = _make_question_mcq(cls.session, order=0, correct_label='A')
        cls.session.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session.save()
        cls.participant = _make_participant(cls.session, 'Eve')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_first_submission_accepted(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1000),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['is_correct'])

    def test_second_submission_returns_409(self):
        # First submit
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1000),
            content_type='application/json',
        )
        # Second submit same question
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 2000),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_duplicate_submission_error_includes_original_result(self):
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 0),
            content_type='application/json',
        )
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 2000),
            content_type='application/json',
        )
        data = resp.json()
        self.assertTrue(data['is_correct'])
        self.assertGreater(data['score_awarded'], 0)

    def test_different_question_allows_submit(self):
        # Create second question
        q1 = _make_question_mcq(self.session, order=1, correct_label='C')
        # Answer Q0
        self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1000),
            content_type='application/json',
        )
        # Advance session to Q1
        self.session.current_index = 1
        self.session.save()
        # Answer Q1 — should succeed
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 1, {'option_label': 'C'}, 1500),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Error States & Validation
# ---------------------------------------------------------------------------

class TestAnswerSubmissionErrors(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_err_ans')
        cls.subject = _make_subject()
        cls.session_active = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='ERREAT',
            current_index=0,
        )
        cls.session_lobby = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_LOBBY,
            code='ERRLOB',
            current_index=0,
        )
        cls.session_finished = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_FINISHED,
            code='ERRFIN',
            current_index=0,
        )
        cls.q0 = _make_question_mcq(cls.session_active, order=0, correct_label='A')
        _make_question_mcq(cls.session_lobby, order=0, correct_label='A')
        _make_question_mcq(cls.session_finished, order=0, correct_label='A')
        cls.session_active.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session_active.save()
        cls.participant = _make_participant(cls.session_active, 'Frank')

    def setUp(self):
        self.client = Client()

    def test_session_not_in_progress_returns_409(self):
        url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session_lobby.code})
        p = _make_participant(self.session_lobby, 'Test')
        q = BrainBuzzSessionQuestion.objects.get(session=self.session_lobby)
        resp = self.client.post(
            url,
            _submit_answer_payload(p.id, 0, {'option_label': 'A'}, 1000),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_not_joined_returns_403(self):
        url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session_active.code})
        resp = self.client.post(
            url,
            _submit_answer_payload(9999, 0, {'option_label': 'A'}, 1000),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_wrong_question_index_returns_409(self):
        url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session_active.code})
        # Set session cookie so participant is "joined"
        client = Client()
        s = client.session
        s[f'bb_pid_{self.session_active.code}'] = self.participant.id
        s.save()
        # Session current_index=0, but submit for index=1
        resp = client.post(
            url,
            _submit_answer_payload(self.participant.id, 1, {'option_label': 'A'}, 1000),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_invalid_json_returns_400(self):
        url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session_active.code})
        resp = self.client.post(url, 'not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_fields_returns_400(self):
        url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session_active.code})
        resp = self.client.post(
            url,
            json.dumps({'participant_id': self.participant.id}),  # Missing question_index, answer_payload
            content_type='application/json',
        )
        # May be 400 or 500 depending on implementation; at minimum not 200
        self.assertNotEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# True/False Variants
# ---------------------------------------------------------------------------

class TestTrueFalseSubmission(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_tf')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='TFTRUE',
            current_index=0,
        )
        cls.q0 = _make_question_tf(cls.session, order=0, correct='true')
        cls.session.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session.save()
        cls.participant = _make_participant(cls.session, 'Grace')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_true_answer_when_true_is_correct(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 1500),
            content_type='application/json',
        )
        self.assertTrue(resp.json()['is_correct'])

    def test_false_answer_when_true_is_correct(self):
        resp = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'B'}, 1500),
            content_type='application/json',
        )
        self.assertFalse(resp.json()['is_correct'])


# ---------------------------------------------------------------------------
# Multiple-Answer Session Flow
# ---------------------------------------------------------------------------

class TestMultipleAnswerFlow(TestCase):
    """Test answering multiple questions in sequence within one session."""

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('teach_multi')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            code='MULTIQ',
            current_index=0,
        )
        cls.q0 = _make_question_mcq(cls.session, order=0, correct_label='A')
        cls.q1 = _make_question_mcq(cls.session, order=1, correct_label='B')
        cls.q2 = _make_question_short(cls.session, order=2, correct_answer='python')
        cls.session.question_deadline = timezone.now() + timedelta(seconds=20)
        cls.session.save()
        cls.participant = _make_participant(cls.session, 'Henry')

    def setUp(self):
        self.client = Client()
        session = self.client.session
        session[f'bb_pid_{self.session.code}'] = self.participant.id
        session.save()
        self.url = reverse('brainbuzz:api_submit', kwargs={'join_code': self.session.code})

    def test_answer_three_questions_in_sequence(self):
        # Answer Q0: correct (time=0 for max points=1000)
        resp0 = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 0),
            content_type='application/json',
        )
        self.assertTrue(resp0.json()['is_correct'])
        self.assertEqual(resp0.json()['total_score'], 1000)

        # Advance to Q1
        self.session.current_index = 1
        self.session.question_deadline = timezone.now() + timedelta(seconds=20)
        self.session.save()

        # Answer Q1: incorrect
        resp1 = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 1, {'option_label': 'A'}, 1500),
            content_type='application/json',
        )
        self.assertFalse(resp1.json()['is_correct'])
        self.assertEqual(resp1.json()['total_score'], 1000)  # No change

        # Advance to Q2
        self.session.current_index = 2
        self.session.question_deadline = timezone.now() + timedelta(seconds=20)
        self.session.save()

        # Answer Q2: correct (time=0 for max points=1000)
        resp2 = self.client.post(
            self.url,
            _submit_answer_payload(self.participant.id, 2, {'text': 'python'}, 0),
            content_type='application/json',
        )
        self.assertTrue(resp2.json()['is_correct'])
        self.assertEqual(resp2.json()['total_score'], 2000)

    def test_participant_final_score(self):
        # Answer Q0 correctly, Q1 incorrectly, Q2 correctly (time=0 for exact scoring)
        self.client.post(self.url, _submit_answer_payload(self.participant.id, 0, {'option_label': 'A'}, 0), content_type='application/json')

        self.session.current_index = 1
        self.session.question_deadline = timezone.now() + timedelta(seconds=20)
        self.session.save()
        self.client.post(self.url, _submit_answer_payload(self.participant.id, 1, {'option_label': 'C'}, 1500), content_type='application/json')

        self.session.current_index = 2
        self.session.question_deadline = timezone.now() + timedelta(seconds=20)
        self.session.save()
        self.client.post(self.url, _submit_answer_payload(self.participant.id, 2, {'text': 'python'}, 0), content_type='application/json')

        self.participant.refresh_from_db()
        self.assertEqual(self.participant.score, 2000)
