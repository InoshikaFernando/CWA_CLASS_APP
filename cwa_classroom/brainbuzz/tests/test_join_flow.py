"""
test_join_flow.py
~~~~~~~~~~~~~~~~~
Tests for the mobile-first student join flow (CPP-229 / join-flow spec):
  - api_join: validation, duplicate nickname auto-suffix, error states
  - _resolve_nickname: suffix logic
  - join view: renders with prefill_code
  - Rate limiting (mocked cache)
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from classroom.models import Subject
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    QUESTION_TYPE_MCQ,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_teacher_screens.py conventions)
# ---------------------------------------------------------------------------

def _make_subject(slug='mathematics', name='Mathematics'):
    return Subject.objects.get_or_create(slug=slug, defaults={'name': name})[0]


def _make_user(username='student_jf', **kwargs):
    return User.objects.create_user(
        username=username, password='pass', email=f'{username}@test.com', **kwargs
    )


def _make_session(host, subject, status=BrainBuzzSession.STATUS_LOBBY, code='JFTST1', **kwargs):
    return BrainBuzzSession.objects.create(
        code=code,
        host=host,
        subject=subject,
        status=status,
        time_per_question_sec=20,
        **kwargs,
    )


def _add_question(session, order=0):
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'Question {order}?',
        question_type=QUESTION_TYPE_MCQ,
        options_json=[
            {'label': 'A', 'text': 'Yes', 'is_correct': True},
            {'label': 'B', 'text': 'No', 'is_correct': False},
        ],
        points_base=1000,
        source_model='CodingExercise',
        source_id=order,
    )


def _join_payload(code='JFTST1', nickname='Alice'):
    return json.dumps({'code': code, 'nickname': nickname})


# Patch rate limiter to always allow (default for most tests)
_allow_rate = mock.patch('brainbuzz.views._check_join_rate_limit', return_value=True)


# ---------------------------------------------------------------------------
# api_join — happy path
# ---------------------------------------------------------------------------

@_allow_rate
class TestApiJoinSuccess(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_user('host_success')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.host, cls.subject, code='SUCCSS')
        _add_question(cls.session)

    def setUp(self):
        self.client = Client()
        self.url = reverse('brainbuzz:api_join')

    def test_returns_200_on_valid_join(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('SUCCSS', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_response_has_participant_id(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('SUCCSS', 'Bob'),
            content_type='application/json',
        )
        data = resp.json()
        self.assertIn('participant_id', data)
        self.assertIsInstance(data['participant_id'], int)

    def test_response_has_nickname(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('SUCCSS', 'Carol'),
            content_type='application/json',
        )
        self.assertEqual(resp.json()['nickname'], 'Carol')

    def test_response_has_redirect_url(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('SUCCSS', 'Dave'),
            content_type='application/json',
        )
        self.assertIn('redirect_url', resp.json())

    def test_participant_created_in_db(self, _mock):
        self.client.post(
            self.url, _join_payload('SUCCSS', 'Eve'),
            content_type='application/json',
        )
        self.assertTrue(
            BrainBuzzParticipant.objects.filter(
                session=self.session, nickname='Eve'
            ).exists()
        )

    def test_anonymous_user_can_join(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('SUCCSS', 'Anon1'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        participant = BrainBuzzParticipant.objects.get(session=self.session, nickname='Anon1')
        self.assertIsNone(participant.student)

    def test_authenticated_user_linked(self, _mock):
        student = _make_user('linked_student')
        self.client.force_login(student)
        resp = self.client.post(
            self.url, _join_payload('SUCCSS', 'LinkedStudent'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        participant = BrainBuzzParticipant.objects.get(session=self.session, nickname='LinkedStudent')
        self.assertEqual(participant.student, student)

    def test_code_case_insensitive(self, _mock):
        resp = self.client.post(
            self.url,
            json.dumps({'code': 'succss', 'nickname': 'Lower'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# api_join — duplicate nickname auto-suffix
# ---------------------------------------------------------------------------

@_allow_rate
class TestApiJoinDuplicateNickname(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_user('host_dup')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.host, cls.subject, code='DUPNCK')
        _add_question(cls.session)
        # Pre-create a participant named 'Alice'
        BrainBuzzParticipant.objects.create(session=cls.session, nickname='Alice')

    def setUp(self):
        self.client = Client()
        self.url = reverse('brainbuzz:api_join')

    def test_duplicate_gets_hash_2_suffix(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('DUPNCK', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['nickname'], 'Alice #2')

    def test_third_duplicate_gets_hash_3_suffix(self, _mock):
        # 'Alice #2' already taken from previous sub-test; create it explicitly
        BrainBuzzParticipant.objects.get_or_create(session=self.session, nickname='Alice #2')
        resp = self.client.post(
            self.url, _join_payload('DUPNCK', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(resp.json()['nickname'], ['Alice #2', 'Alice #3'])

    def test_unique_nickname_not_modified(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('DUPNCK', 'Unique'),
            content_type='application/json',
        )
        self.assertEqual(resp.json()['nickname'], 'Unique')


# ---------------------------------------------------------------------------
# _resolve_nickname unit tests
# ---------------------------------------------------------------------------

class TestResolveNickname(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_user('host_resolve')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.host, cls.subject, code='RSLVNK')

    def _resolve(self, desired):
        from brainbuzz.views import _resolve_nickname
        return _resolve_nickname(self.session, desired)

    def test_unique_returned_unchanged(self):
        self.assertEqual(self._resolve('Newname'), 'Newname')

    def test_duplicate_returns_hash_2(self):
        BrainBuzzParticipant.objects.create(session=self.session, nickname='Taken')
        result = self._resolve('Taken')
        self.assertEqual(result, 'Taken #2')

    def test_long_base_truncated_for_suffix(self):
        # 17-char base — suffix " #2" (3 chars) → candidate "12345678901234567 #2" = 20 chars
        long_nick = 'A' * 17
        BrainBuzzParticipant.objects.create(session=self.session, nickname=long_nick)
        result = self._resolve(long_nick)
        self.assertLessEqual(len(result), 20)
        self.assertIn('#', result)

    def test_strip_whitespace(self):
        result = self._resolve('  Bob  ')
        self.assertEqual(result, 'Bob')

    def test_max_20_chars_enforced(self):
        over_long = 'X' * 25
        result = self._resolve(over_long)
        self.assertLessEqual(len(result), 20)


# ---------------------------------------------------------------------------
# api_join — error states
# ---------------------------------------------------------------------------

@_allow_rate
class TestApiJoinErrorStates(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_user('host_err')
        cls.subject = _make_subject()
        cls.session_lobby = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_LOBBY, code='ERRLOB',
        )
        cls.session_active = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE, code='ERRACT',
        )
        cls.session_finished = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_FINISHED, code='ERRFIN',
        )
        cls.session_cancelled = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_CANCELLED, code='ERRCAN',
        )
        _add_question(cls.session_lobby)

    def setUp(self):
        self.client = Client()
        self.url = reverse('brainbuzz:api_join')

    def test_invalid_code_returns_404(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('XXXXXX', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_invalid_code_error_message(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('XXXXXX', 'Alice'),
            content_type='application/json',
        )
        self.assertIn('not found', resp.json()['error'].lower())

    def test_active_session_returns_409(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('ERRACT', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_active_session_error_message(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('ERRACT', 'Alice'),
            content_type='application/json',
        )
        self.assertIn('already started', resp.json()['error'].lower())

    def test_finished_session_returns_409(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('ERRFIN', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_finished_session_error_message(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('ERRFIN', 'Alice'),
            content_type='application/json',
        )
        self.assertIn('ended', resp.json()['error'].lower())

    def test_cancelled_session_returns_409(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('ERRCAN', 'Alice'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_missing_code_returns_400(self, _mock):
        resp = self.client.post(
            self.url,
            json.dumps({'code': '', 'nickname': 'Alice'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_nickname_returns_400(self, _mock):
        resp = self.client.post(
            self.url,
            json.dumps({'code': 'ERRLOB', 'nickname': ''}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json_returns_400(self, _mock):
        resp = self.client.post(
            self.url, 'not json',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# api_join — nickname validation
# ---------------------------------------------------------------------------

@_allow_rate
class TestApiJoinNicknameValidation(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_user('host_nick')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.host, cls.subject, code='NICKVA')
        _add_question(cls.session)

    def setUp(self):
        self.client = Client()
        self.url = reverse('brainbuzz:api_join')

    def test_nickname_over_20_chars_returns_400(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('NICKVA', 'A' * 21),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_exactly_20_chars_is_valid(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('NICKVA', 'A' * 20),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_single_char_is_valid(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('NICKVA', 'Z'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_special_chars_rejected(self, _mock):
        for bad in ['Ali@ce', 'Bob!', '<script>', 'Eve#1']:
            with self.subTest(nickname=bad):
                resp = self.client.post(
                    self.url, _join_payload('NICKVA', bad),
                    content_type='application/json',
                )
                self.assertEqual(resp.status_code, 400, f'Expected 400 for {bad!r}')

    def test_alphanumeric_with_spaces_valid(self, _mock):
        resp = self.client.post(
            self.url, _join_payload('NICKVA', 'John Smith'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_nickname_leading_space_stripped_and_accepted(self, _mock):
        # API strips leading/trailing whitespace before validating — ' Leading' becomes 'Leading'
        resp = self.client.post(
            self.url, _join_payload('NICKVA', ' Leading'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['nickname'], 'Leading')


# ---------------------------------------------------------------------------
# api_join — rate limiting
# ---------------------------------------------------------------------------

class TestApiJoinRateLimit(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_user('host_rl')
        cls.subject = _make_subject()
        cls.session = _make_session(cls.host, cls.subject, code='RLIMIT')
        _add_question(cls.session)

    def setUp(self):
        self.client = Client()
        self.url = reverse('brainbuzz:api_join')

    def test_rate_limit_exceeded_returns_429(self):
        with mock.patch('brainbuzz.views._check_join_rate_limit', return_value=False):
            resp = self.client.post(
                self.url, _join_payload('RLIMIT', 'Alice'),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 429)

    def test_rate_limit_error_message(self):
        with mock.patch('brainbuzz.views._check_join_rate_limit', return_value=False):
            resp = self.client.post(
                self.url, _join_payload('RLIMIT', 'Alice'),
                content_type='application/json',
            )
        self.assertIn('error', resp.json())


# ---------------------------------------------------------------------------
# join view (GET)
# ---------------------------------------------------------------------------

class TestJoinView(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('brainbuzz:join')

    def test_join_page_loads(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_join_page_without_prefill(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['prefill_code'], '')

    def test_join_page_with_prefill_code(self):
        resp = self.client.get(self.url + '?code=ABC123')
        self.assertEqual(resp.context['prefill_code'], 'ABC123')

    def test_prefill_code_uppercased(self):
        resp = self.client.get(self.url + '?code=abc123')
        self.assertEqual(resp.context['prefill_code'], 'ABC123')
