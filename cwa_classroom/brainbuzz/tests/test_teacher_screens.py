"""
test_teacher_screens.py
~~~~~~~~~~~~~~~~~~~~~~~
Tests for CPP-235 teacher in-session screens:
  - State machine: reveal, next-from-reveal, next-from-active (skip reveal)
  - api_session_state payload: answers_received, answer_distribution
  - Distribution builder: MCQ by option_label, SA binary
  - teacher screen redirects (LOBBY/ACTIVE/REVEAL/FINISHED → correct view)
  - teacher_end view: annotated correct_count + avg_response_ms
  - export_csv: new columns
  - repeat_session: creates new session from config_json
"""
import json
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
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_subject(slug='mathematics', name='Mathematics'):
    return Subject.objects.get_or_create(slug=slug, defaults={'name': name})[0]


def _make_teacher(username='teacher_bb'):
    return User.objects.create_user(username=username, password='pass', email=f'{username}@bb.test')


def _make_session(host, subject, status=BrainBuzzSession.STATUS_LOBBY, code='AABBCC', **kwargs):
    """code is a proper named param — callers may override it without collision."""
    return BrainBuzzSession.objects.create(
        code=code,
        host=host,
        subject=subject,
        status=status,
        time_per_question_sec=20,
        **kwargs,
    )


def _add_question(session, order, question_type=QUESTION_TYPE_MCQ, options=None, correct_short_answer=None):
    if options is None and question_type == QUESTION_TYPE_MCQ:
        options = [
            {'label': 'A', 'text': 'Option A', 'is_correct': True},
            {'label': 'B', 'text': 'Option B', 'is_correct': False},
            {'label': 'C', 'text': 'Option C', 'is_correct': False},
            {'label': 'D', 'text': 'Option D', 'is_correct': False},
        ]
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'Question {order}?',
        question_type=question_type,
        options_json=options or [],
        correct_short_answer=correct_short_answer,
        points_base=1000,
        source_model='CodingExercise',
        source_id=order,
    )


def _add_participant(session, nickname='Alice'):
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _add_answer(participant, session_question, label=None, text=None, is_correct=False, ms=500):
    return BrainBuzzAnswer.objects.create(
        participant=participant,
        session_question=session_question,
        selected_option_label=label,
        short_answer_text=text,
        time_taken_ms=ms,
        points_awarded=1000 if is_correct else 0,
        is_correct=is_correct,
    )


# Patch _require_teacher to always allow access.
# Applied at class level — Django's test runner injects mock only into test_* methods,
# NOT into setUp/setUpClass. setUp must have signature (self) only.
_patch_teacher = mock.patch('brainbuzz.views._require_teacher', return_value=True)


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------

@_patch_teacher
class TestRevealAction(TestCase):
    """ACTIVE → REVEAL via 'reveal' action."""

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_reveal')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            current_index=0,
            state_version=1,
        )
        _add_question(cls.session, 0)
        _add_question(cls.session, 1)
        cls.session.question_deadline = timezone.now()
        cls.session.save()

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def _post(self, action, index=0):
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': self.session.code})
        return self.client.post(
            url,
            data=json.dumps({'action': action, 'expected_current_index': index}),
            content_type='application/json',
        )

    def test_reveal_transitions_active_to_reveal(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.save()
        resp = self._post('reveal', 0)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'reveal')

    def test_reveal_clears_deadline(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.question_deadline = timezone.now()
        self.session.save()
        self._post('reveal', 0)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.question_deadline)

    def test_reveal_increments_state_version(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.save()
        old_ver = BrainBuzzSession.objects.get(pk=self.session.pk).state_version
        self._post('reveal', 0)
        self.session.refresh_from_db()
        self.assertGreater(self.session.state_version, old_ver)

    def test_reveal_noop_when_not_active(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_LOBBY
        self.session.save()
        resp = self._post('reveal', 0)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'lobby')
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.save()

    def test_reveal_idempotency_wrong_index(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.save()
        self._post('reveal', 99)  # wrong index
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, BrainBuzzSession.STATUS_ACTIVE)


@_patch_teacher
class TestNextFromReveal(TestCase):
    """REVEAL + 'next' → ACTIVE(q+1) or FINISHED."""

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_next_reveal')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_REVEAL,
            current_index=0,
            state_version=2,
            code='REVEAL',
        )
        _add_question(cls.session, 0)
        _add_question(cls.session, 1)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def _post(self, action, index=0):
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': self.session.code})
        return self.client.post(
            url,
            data=json.dumps({'action': action, 'expected_current_index': index}),
            content_type='application/json',
        )

    def test_next_from_reveal_moves_to_active_q1(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_REVEAL
        self.session.current_index = 0
        self.session.save()
        resp = self._post('next', 0)
        data = resp.json()
        self.assertEqual(data['status'], 'active')
        self.assertEqual(data['current_index'], 1)

    def test_next_from_reveal_sets_deadline(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_REVEAL
        self.session.current_index = 0
        self.session.question_deadline = None
        self.session.save()
        self._post('next', 0)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.question_deadline)

    def test_next_from_reveal_on_last_question_finishes(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_REVEAL
        self.session.current_index = 1
        self.session.save()
        resp = self._post('next', 1)
        self.assertEqual(resp.json()['status'], 'finished')


@_patch_teacher
class TestNextFromActive(TestCase):
    """ACTIVE + 'next' skips REVEAL and goes directly to next question."""

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_next_active')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            current_index=0,
            code='NEXTAC',
        )
        _add_question(cls.session, 0)
        _add_question(cls.session, 1)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def _post(self, action, index=0):
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': self.session.code})
        return self.client.post(
            url,
            data=json.dumps({'action': action, 'expected_current_index': index}),
            content_type='application/json',
        )

    def test_next_from_active_goes_to_active_q1(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.save()
        resp = self._post('next', 0)
        data = resp.json()
        self.assertEqual(data['status'], 'active')
        self.assertEqual(data['current_index'], 1)

    def test_next_from_active_last_question_finishes(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 1
        self.session.save()
        resp = self._post('next', 1)
        self.assertEqual(resp.json()['status'], 'finished')


# ---------------------------------------------------------------------------
# Payload: answers_received + answer_distribution
# ---------------------------------------------------------------------------

@_patch_teacher
class TestStatePayloadAnswersReceived(TestCase):
    """answers_received is always present in the state payload."""

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_payload')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            current_index=0,
            code='PAYLOD',
        )
        cls.q0 = _add_question(cls.session, 0)
        cls.participant = _add_participant(cls.session, 'Bob')
        _add_answer(cls.participant, cls.q0, label='A', is_correct=True)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def test_answers_received_count(self, _mock):
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        data = resp.json()
        self.assertIn('answers_received', data)
        self.assertEqual(data['answers_received'], 1)

    def test_answer_distribution_empty_when_active(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.save()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertEqual(resp.json()['answer_distribution'], [])

    def test_answer_distribution_populated_when_reveal(self, _mock):
        self.session.status = BrainBuzzSession.STATUS_REVEAL
        self.session.save()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        dist = resp.json()['answer_distribution']
        self.assertIsInstance(dist, list)
        self.assertGreater(len(dist), 0)
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.save()


# ---------------------------------------------------------------------------
# Distribution builder
# ---------------------------------------------------------------------------

class TestBuildDistribution(TestCase):
    """Unit-test _build_distribution helper directly."""

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_dist')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_REVEAL,
            current_index=0,
            code='DISTRI',
        )
        cls.q_mcq = _add_question(cls.session, 0, QUESTION_TYPE_MCQ)
        cls.q_sa = _add_question(
            cls.session, 1, QUESTION_TYPE_SHORT_ANSWER,
            options=[], correct_short_answer='python',
        )
        cls.p1 = _add_participant(cls.session, 'P1')
        cls.p2 = _add_participant(cls.session, 'P2')
        cls.p3 = _add_participant(cls.session, 'P3')
        _add_answer(cls.p1, cls.q_mcq, label='A', is_correct=True)
        _add_answer(cls.p2, cls.q_mcq, label='A', is_correct=True)
        _add_answer(cls.p3, cls.q_mcq, label='B', is_correct=False)
        _add_answer(cls.p1, cls.q_sa, text='python', is_correct=True)
        _add_answer(cls.p2, cls.q_sa, text='java', is_correct=False)

    def test_mcq_distribution_counts(self):
        from brainbuzz.views import _build_distribution
        dist = _build_distribution(self.session, self.q_mcq)
        counts = {d['label']: d['count'] for d in dist}
        self.assertEqual(counts.get('A'), 2)
        self.assertEqual(counts.get('B'), 1)
        self.assertEqual(counts.get('C', 0), 0)

    def test_mcq_distribution_correct_flag(self):
        from brainbuzz.views import _build_distribution
        dist = _build_distribution(self.session, self.q_mcq)
        a_entry = next(d for d in dist if d['label'] == 'A')
        b_entry = next(d for d in dist if d['label'] == 'B')
        self.assertTrue(a_entry['is_correct'])
        self.assertFalse(b_entry['is_correct'])

    def test_sa_distribution_binary(self):
        from brainbuzz.views import _build_distribution
        dist = _build_distribution(self.session, self.q_sa)
        self.assertEqual(len(dist), 2)
        correct_entry = next(d for d in dist if d['is_correct'])
        incorrect_entry = next(d for d in dist if not d['is_correct'])
        self.assertEqual(correct_entry['count'], 1)
        self.assertEqual(incorrect_entry['count'], 1)

    def test_distribution_none_question(self):
        from brainbuzz.views import _build_distribution
        self.assertEqual(_build_distribution(self.session, None), [])


# ---------------------------------------------------------------------------
# Teacher screen redirect tests
# ---------------------------------------------------------------------------

@_patch_teacher
class TestTeacherScreenRedirects(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_redirect')
        cls.subject = _make_subject()

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def _lobby_url(self, code):
        return reverse('brainbuzz:teacher_lobby', kwargs={'join_code': code})

    def _ingame_url(self, code):
        return reverse('brainbuzz:teacher_ingame', kwargs={'join_code': code})

    def test_lobby_redirects_to_ingame_when_active(self, _mock):
        s = _make_session(self.host, self.subject, status=BrainBuzzSession.STATUS_ACTIVE, code='RA2233')
        resp = self.client.get(self._lobby_url(s.code))
        self.assertRedirects(resp, self._ingame_url(s.code), fetch_redirect_response=False)

    def test_lobby_redirects_to_ingame_when_reveal(self, _mock):
        s = _make_session(self.host, self.subject, status=BrainBuzzSession.STATUS_REVEAL, code='RB2244')
        resp = self.client.get(self._lobby_url(s.code))
        self.assertRedirects(resp, self._ingame_url(s.code), fetch_redirect_response=False)

    def test_lobby_redirects_to_end_when_finished(self, _mock):
        s = _make_session(self.host, self.subject, status=BrainBuzzSession.STATUS_FINISHED, code='RC2255')
        resp = self.client.get(self._lobby_url(s.code))
        end_url = reverse('brainbuzz:teacher_end', kwargs={'join_code': s.code})
        self.assertRedirects(resp, end_url, fetch_redirect_response=False)

    def test_ingame_redirects_to_lobby_when_lobby(self, _mock):
        s = _make_session(self.host, self.subject, status=BrainBuzzSession.STATUS_LOBBY, code='RD2266')
        resp = self.client.get(self._ingame_url(s.code))
        self.assertRedirects(resp, self._lobby_url(s.code), fetch_redirect_response=False)

    def test_ingame_redirects_to_end_when_finished(self, _mock):
        s = _make_session(self.host, self.subject, status=BrainBuzzSession.STATUS_FINISHED, code='RE2277')
        resp = self.client.get(self._ingame_url(s.code))
        end_url = reverse('brainbuzz:teacher_end', kwargs={'join_code': s.code})
        self.assertRedirects(resp, end_url, fetch_redirect_response=False)

    def test_ingame_renders_when_reveal(self, _mock):
        s = _make_session(self.host, self.subject, status=BrainBuzzSession.STATUS_REVEAL, code='RF2288')
        resp = self.client.get(self._ingame_url(s.code))
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# teacher_end view: annotated stats
# ---------------------------------------------------------------------------

@_patch_teacher
class TestTeacherEnd(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_end')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_FINISHED,
            code='END123',
        )
        cls.q0 = _add_question(cls.session, 0)
        cls.q1 = _add_question(cls.session, 1)
        cls.p = _add_participant(cls.session, 'Charlie')
        _add_answer(cls.p, cls.q0, label='A', is_correct=True, ms=800)
        _add_answer(cls.p, cls.q1, label='B', is_correct=False, ms=1200)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def test_end_page_loads(self, _mock):
        url = reverse('brainbuzz:teacher_end', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_leaderboard_has_correct_count(self, _mock):
        url = reverse('brainbuzz:teacher_end', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        leaderboard = resp.context['leaderboard']
        self.assertEqual(len(leaderboard), 1)
        self.assertEqual(leaderboard[0].correct_count, 1)

    def test_leaderboard_has_avg_response_ms(self, _mock):
        url = reverse('brainbuzz:teacher_end', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        avg = resp.context['leaderboard'][0].avg_response_ms
        self.assertAlmostEqual(avg, 1000.0, delta=1)

    def test_page_shows_correct_count_column(self, _mock):
        url = reverse('brainbuzz:teacher_end', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertContains(resp, 'Correct')

    def test_page_shows_avg_ms_column(self, _mock):
        url = reverse('brainbuzz:teacher_end', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertContains(resp, 'Avg')


# ---------------------------------------------------------------------------
# export_csv: new columns
# ---------------------------------------------------------------------------

@_patch_teacher
class TestExportCsv(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_csv')
        cls.subject = _make_subject()
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_FINISHED,
            code='CSV123',
        )
        cls.q0 = _add_question(cls.session, 0)
        cls.p = _add_participant(cls.session, 'Dave')
        _add_answer(cls.p, cls.q0, label='A', is_correct=True, ms=600)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def test_csv_has_correct_header(self, _mock):
        url = reverse('brainbuzz:export_csv', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        header_line = resp.content.decode().splitlines()[0]
        self.assertIn('Correct', header_line)
        self.assertIn('Avg Response', header_line)

    def test_csv_data_row_correct_count(self, _mock):
        url = reverse('brainbuzz:export_csv', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        lines = resp.content.decode().splitlines()
        self.assertGreater(len(lines), 1)
        # Rank,Nickname,User,Total Score,Correct,Avg Response (ms),Joined At
        parts = lines[1].split(',')
        self.assertEqual(parts[4], '1')  # Correct = 1


# ---------------------------------------------------------------------------
# repeat_session
# ---------------------------------------------------------------------------

@_patch_teacher
class TestRepeatSession(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = _make_teacher('t_repeat')
        cls.subject = _make_subject(slug='coding', name='Coding')
        cls.session = _make_session(
            cls.host, cls.subject,
            status=BrainBuzzSession.STATUS_FINISHED,
            code='REP123',
            config_json={
                'subject': 'coding',
                'topic_level_id': 999,
                'question_count': 5,
                'time_per_question_sec': 15,
            },
        )
        _add_question(cls.session, 0)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.host)

    def test_repeat_session_copies_config(self, _mock):
        with mock.patch('brainbuzz.views._snapshot_coding_questions') as mock_snap:
            def fake_snap(session, topic_level_id, count):
                _add_question(session, 0)
            mock_snap.side_effect = fake_snap

            url = reverse('brainbuzz:repeat_session', kwargs={'join_code': self.session.code})
            self.client.post(url)

        new_sessions = BrainBuzzSession.objects.exclude(pk=self.session.pk).filter(host=self.host)
        self.assertTrue(new_sessions.exists())
        new = new_sessions.latest('created_at')
        self.assertEqual(new.config_json['subject'], 'coding')
        self.assertEqual(new.time_per_question_sec, 15)

    def test_repeat_session_requires_post(self, _mock):
        url = reverse('brainbuzz:repeat_session', kwargs={'join_code': self.session.code})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 405)

    def test_repeat_redirects_to_create_if_no_config(self, _mock):
        self.session.config_json = {}
        self.session.save()
        url = reverse('brainbuzz:repeat_session', kwargs={'join_code': self.session.code})
        resp = self.client.post(url)
        create_url = reverse('brainbuzz:create')
        self.assertRedirects(resp, create_url, fetch_redirect_response=False)
        self.session.config_json = {
            'subject': 'coding', 'topic_level_id': 999,
            'question_count': 5, 'time_per_question_sec': 15,
        }
        self.session.save()
