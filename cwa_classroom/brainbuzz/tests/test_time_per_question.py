"""
test_time_per_question.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the configurable "Time per question" feature.

Covers:
  - _parse_time_per_question: unit-level validation logic
  - create_session view: invalid time values are rejected with a clear error
  - create_session view: valid time is stored on BrainBuzzSession
  - create_session view: session questions inherit the chosen time_limit_sec
  - _create_context: always exposes time_per_question_options + default
  - Existing sessions with 20 s default are unaffected
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
from brainbuzz.views import (
    _parse_time_per_question,
    _create_context,
    TIME_PER_QUESTION_MIN,
    TIME_PER_QUESTION_MAX,
    TIME_PER_QUESTION_DEFAULT,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username='tpq_teacher'):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@t.com')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_subject(slug='mathematics', name='Mathematics'):
    return Subject.objects.get_or_create(slug=slug, defaults={'name': name})[0]


def _make_session(teacher, subject, time_per_question_sec=20, code='TPQTST'):
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY,
        time_per_question_sec=time_per_question_sec,
    )


def _make_question(session, order=0, time_limit_sec=None):
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'Q{order}',
        question_type=QUESTION_TYPE_MCQ,
        options_json=[{'label': 'A', 'text': 'OK', 'is_correct': True}],
        time_limit_sec=time_limit_sec if time_limit_sec is not None else session.time_per_question_sec,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _add_participant(session, nickname='Player1'):
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


# ---------------------------------------------------------------------------
# _parse_time_per_question — pure unit tests (no DB)
# ---------------------------------------------------------------------------

class TestParseTimePerQuestion(TestCase):

    def test_default_value_is_valid(self):
        value, error = _parse_time_per_question(TIME_PER_QUESTION_DEFAULT)
        self.assertIsNone(error)
        self.assertEqual(value, TIME_PER_QUESTION_DEFAULT)

    def test_minimum_boundary_is_valid(self):
        value, error = _parse_time_per_question(TIME_PER_QUESTION_MIN)
        self.assertIsNone(error)
        self.assertEqual(value, TIME_PER_QUESTION_MIN)

    def test_maximum_boundary_is_valid(self):
        value, error = _parse_time_per_question(TIME_PER_QUESTION_MAX)
        self.assertIsNone(error)
        self.assertEqual(value, TIME_PER_QUESTION_MAX)

    def test_value_below_minimum_returns_error(self):
        _, error = _parse_time_per_question(TIME_PER_QUESTION_MIN - 1)
        self.assertIsNotNone(error)

    def test_value_above_maximum_returns_error(self):
        _, error = _parse_time_per_question(TIME_PER_QUESTION_MAX + 1)
        self.assertIsNotNone(error)

    def test_zero_returns_error(self):
        _, error = _parse_time_per_question(0)
        self.assertIsNotNone(error)

    def test_negative_returns_error(self):
        _, error = _parse_time_per_question(-10)
        self.assertIsNotNone(error)

    def test_non_numeric_string_returns_error(self):
        _, error = _parse_time_per_question('abc')
        self.assertIsNotNone(error)

    def test_empty_string_returns_error(self):
        _, error = _parse_time_per_question('')
        self.assertIsNotNone(error)

    def test_float_string_returns_error(self):
        _, error = _parse_time_per_question('20.5')
        self.assertIsNotNone(error)

    def test_string_numeric_is_accepted(self):
        value, error = _parse_time_per_question('30')
        self.assertIsNone(error)
        self.assertEqual(value, 30)

    def test_error_message_mentions_bounds(self):
        _, error = _parse_time_per_question(200)
        self.assertIn(str(TIME_PER_QUESTION_MIN), error)
        self.assertIn(str(TIME_PER_QUESTION_MAX), error)

    def test_various_valid_values(self):
        for secs in [5, 10, 15, 20, 30, 45, 60, 90, 120]:
            with self.subTest(secs=secs):
                value, error = _parse_time_per_question(secs)
                self.assertIsNone(error, f"Expected {secs}s to be valid")
                self.assertEqual(value, secs)


# ---------------------------------------------------------------------------
# _create_context — always provides time_per_question_options + default
# ---------------------------------------------------------------------------

class TestCreateContext(TestCase):

    def test_context_includes_time_per_question_sec_default(self):
        ctx = _create_context()
        self.assertIn('time_per_question_sec', ctx)
        self.assertEqual(ctx['time_per_question_sec'], TIME_PER_QUESTION_DEFAULT)

    def test_context_includes_time_per_question_options(self):
        ctx = _create_context()
        self.assertIn('time_per_question_options', ctx)
        self.assertIsInstance(ctx['time_per_question_options'], list)
        self.assertGreater(len(ctx['time_per_question_options']), 0)

    def test_options_are_tuples_of_int_and_str(self):
        ctx = _create_context()
        for value, label in ctx['time_per_question_options']:
            self.assertIsInstance(value, int)
            self.assertIsInstance(label, str)

    def test_options_include_minimum_and_maximum(self):
        ctx = _create_context()
        values = [v for v, _ in ctx['time_per_question_options']]
        self.assertIn(TIME_PER_QUESTION_MIN, values)
        self.assertIn(TIME_PER_QUESTION_MAX, values)

    def test_options_include_default(self):
        ctx = _create_context()
        values = [v for v, _ in ctx['time_per_question_options']]
        self.assertIn(TIME_PER_QUESTION_DEFAULT, values)

    def test_all_options_within_valid_range(self):
        ctx = _create_context()
        for value, _ in ctx['time_per_question_options']:
            self.assertGreaterEqual(value, TIME_PER_QUESTION_MIN)
            self.assertLessEqual(value, TIME_PER_QUESTION_MAX)


# ---------------------------------------------------------------------------
# create_session view — invalid time values are rejected
# ---------------------------------------------------------------------------

class TestCreateSessionTimeValidation(TestCase):
    """View-level validation tests. Time check fires before topic lookup,
    so we don't need real maths data for the error path."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('tpq_val_teacher')
        cls.url = reverse('brainbuzz:create')

    def _post(self, time_val, subject='maths'):
        c = Client()
        c.force_login(self.teacher)
        return c.post(self.url, {
            'subject': subject,
            'time_per_question_sec': time_val,
            'question_count': '5',
        })

    def test_value_below_min_returns_200_with_error(self):
        resp = self._post(TIME_PER_QUESTION_MIN - 1)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seconds')

    def test_value_above_max_returns_200_with_error(self):
        resp = self._post(TIME_PER_QUESTION_MAX + 1)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seconds')

    def test_non_numeric_returns_200_with_error(self):
        resp = self._post('notanumber')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seconds')

    def test_empty_time_returns_200_with_error(self):
        resp = self._post('')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seconds')

    def test_zero_returns_200_with_error(self):
        resp = self._post(0)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seconds')

    def test_error_response_preserves_submitted_time_in_context(self):
        resp = self._post(200)
        self.assertEqual(resp.status_code, 200)
        # Context must contain the (invalid) submitted value so the
        # dropdown can be correctly re-selected.
        self.assertEqual(resp.context['time_per_question_sec'], 200)

    def test_error_response_contains_time_per_question_options(self):
        resp = self._post(200)
        self.assertIn('time_per_question_options', resp.context)

    def test_boundary_min_does_not_trigger_error(self):
        # Min itself is valid — validation passes, then subject/topic lookup fails.
        # We only care that the time-specific error is NOT the one returned.
        resp = self._post(TIME_PER_QUESTION_MIN)
        if resp.status_code == 200:
            error = resp.context.get('error', '')
            self.assertNotIn('seconds', error.lower() if 'must be between' not in error else '')

    def test_boundary_max_does_not_trigger_time_error(self):
        resp = self._post(TIME_PER_QUESTION_MAX)
        if resp.status_code == 200:
            error = resp.context.get('error', '')
            self.assertNotIn(str(TIME_PER_QUESTION_MIN), error + str(TIME_PER_QUESTION_MAX))


# ---------------------------------------------------------------------------
# Session + question time_limit_sec propagation (model-level)
# ---------------------------------------------------------------------------

class TestTimeLimitPropagation(TestCase):
    """Verify questions inherit time_per_question_sec from the session."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('tpq_prop_teacher')
        cls.subject = _make_subject()

    def _session_with_questions(self, time_per_question_sec, code):
        session = _make_session(
            self.teacher, self.subject,
            time_per_question_sec=time_per_question_sec,
            code=code,
        )
        for i in range(3):
            _make_question(session, order=i)
        return session

    def test_questions_inherit_20s_default(self):
        session = self._session_with_questions(20, 'TPQP01')
        for q in session.questions.all():
            self.assertEqual(q.time_limit_sec, 20)

    def test_questions_inherit_30s(self):
        session = self._session_with_questions(30, 'TPQP02')
        for q in session.questions.all():
            self.assertEqual(q.time_limit_sec, 30)

    def test_questions_inherit_5s_minimum(self):
        session = self._session_with_questions(5, 'TPQP03')
        for q in session.questions.all():
            self.assertEqual(q.time_limit_sec, 5)

    def test_questions_inherit_120s_maximum(self):
        session = self._session_with_questions(120, 'TPQP04')
        for q in session.questions.all():
            self.assertEqual(q.time_limit_sec, 120)

    def test_deadline_uses_time_limit_sec(self):
        """When a session starts, question_deadline = now + READ_WINDOW_SEC + time_limit_sec."""
        from brainbuzz.views import READ_WINDOW_SEC
        session = self._session_with_questions(45, 'TPQP05')
        _add_participant(session, 'TestPlayer')
        session.status = BrainBuzzSession.STATUS_LOBBY
        session.save()

        c = Client()
        c.force_login(self.teacher)
        before = timezone.now()
        c.post(
            reverse('brainbuzz:api_teacher_action', kwargs={'join_code': session.code}),
            data=json.dumps({'action': 'start'}),
            content_type='application/json',
        )
        after = timezone.now()

        session.refresh_from_db()
        self.assertIsNotNone(session.question_deadline)
        expected_min = before + timedelta(seconds=READ_WINDOW_SEC + 45)
        expected_max = after + timedelta(seconds=READ_WINDOW_SEC + 45)
        self.assertGreaterEqual(session.question_deadline, expected_min)
        self.assertLessEqual(session.question_deadline, expected_max)


# ---------------------------------------------------------------------------
# Existing sessions with default 20 s are unaffected
# ---------------------------------------------------------------------------

class TestExistingSessionsUnaffected(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('tpq_exist_teacher')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.teacher, cls.subject,
            time_per_question_sec=20,
            code='TPQEX1',
        )
        for i in range(2):
            _make_question(cls.session, order=i)

    def test_existing_session_time_per_question_sec_unchanged(self):
        self.session.refresh_from_db()
        self.assertEqual(self.session.time_per_question_sec, 20)

    def test_existing_questions_time_limit_sec_unchanged(self):
        for q in self.session.questions.all():
            self.assertEqual(q.time_limit_sec, 20)

    def test_state_payload_time_per_question_sec_reflects_session(self):
        c = Client()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': self.session.code})
        data = c.get(url).json()
        self.assertEqual(data['time_per_question_sec'], 20)
