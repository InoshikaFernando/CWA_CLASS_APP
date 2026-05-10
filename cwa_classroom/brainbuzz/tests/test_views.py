"""
Unit tests for BrainBuzz API views.

Covers:
  - api_session_state: versioned polling, 304 on no change
  - api_teacher_action: start / next / end / idempotency
  - api_join: rate limiting, duplicate nickname, invalid code, lobby-only
  - api_submit: deadline enforcement, idempotency, wrong index
  - Role-based access: teacher-only and student-facing endpoints
"""
import json
from datetime import timedelta
from unittest.mock import patch

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
    BrainBuzzAnswer,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_MULTIPLE_CHOICE,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(client, url, payload, csrf_bypass=True):
    return client.post(
        url,
        data=json.dumps(payload),
        content_type='application/json',
        enforce_csrf_checks=not csrf_bypass,
    )


def _get_or_create_subject():
    return Subject.objects.get_or_create(slug='maths-test', defaults={'name': 'Maths Test'})[0]


def _make_teacher(username='bb_teacher'):
    u = User.objects.create_user(username=username, password='testpass', email=f'{username}@test.com')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_student(username='bb_student'):
    u = User.objects.create_user(username=username, password='testpass', email=f'{username}@test.com')
    role, _ = Role.objects.get_or_create(name=Role.STUDENT)
    u.roles.add(role)
    return u


def _make_session(teacher, code='TST001', status=BrainBuzzSession.STATUS_LOBBY, subject=None):
    if subject is None:
        subject = _get_or_create_subject()
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=status,
    )


def _add_question(session, order=0, options=None):
    if options is None:
        options = [
            {'label': 'A', 'text': 'Wrong', 'is_correct': False},
            {'label': 'B', 'text': 'Correct', 'is_correct': True},
        ]
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=f'Question {order}',
        question_type=QUESTION_TYPE_MCQ,
        options_json=options,
        source_model='TestQuestion',
        source_id=order,
    )


def _make_participant(session, nickname='Alice'):
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


# ===========================================================================
# api_session_state
# ===========================================================================

class TestApiSessionState(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()
        cls.session = _make_session(cls.teacher, code='STGAT1')

    def test_returns_full_state(self):
        c = Client()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': 'STGAT1'})
        res = c.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['code'], 'STGAT1')
        self.assertIn('state_version', data)

    def test_304_when_version_unchanged(self):
        c = Client()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': 'STGAT1'})
        version = self.session.state_version
        res = c.get(url + f'?since={version}')
        self.assertEqual(res.status_code, 304)

    def test_200_when_version_changed(self):
        session = _make_session(self.teacher, code='STGAT2')
        version = session.state_version
        session.bump_version()
        c = Client()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': 'STGAT2'})
        res = c.get(url + f'?since={version}')
        self.assertEqual(res.status_code, 200)

    def test_404_for_unknown_code(self):
        c = Client()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': 'XXXXX9'})
        res = c.get(url)
        self.assertEqual(res.status_code, 404)


# ===========================================================================
# api_teacher_action
# ===========================================================================

class TestApiTeacherAction(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='bb_teacher_act')
        cls.student = _make_student()

    def _fresh_session(self, code):
        s = _make_session(self.teacher, code=code)
        _add_question(s, 0)
        _add_question(s, 1)
        return s

    def _active_session(self, code):
        s = _make_session(self.teacher, code=code)
        _add_question(s, 0)
        _add_question(s, 1)
        _make_participant(s, 'TestPlayer')
        s.status = BrainBuzzSession.STATUS_ACTIVE
        s.current_index = 0
        s.question_deadline = timezone.now() + timedelta(seconds=20)
        s.state_version = 1
        s.save()
        return s

    def test_start_transitions_to_active(self):
        s = self._fresh_session('ACTST1')
        _make_participant(s, 'Player1')
        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTST1'})
        res = _post(c, url, {'action': 'start', 'expected_current_index': None})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], BrainBuzzSession.STATUS_ACTIVE)
        self.assertEqual(data['current_index'], 0)
        self.assertEqual(data['state_version'], 1)

    def test_next_advances_to_question_1(self):
        s = self._active_session('ACTNX1')
        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTNX1'})
        res = _post(c, url, {'action': 'next', 'expected_current_index': 0})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['current_index'], 1)

    def test_next_ends_session_when_no_more_questions(self):
        s = _make_session(self.teacher, code='ACTNXE')
        _add_question(s, 0)
        s.status = BrainBuzzSession.STATUS_ACTIVE
        s.current_index = 0
        s.save()

        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTNXE'})
        res = _post(c, url, {'action': 'next', 'expected_current_index': 0})
        data = res.json()
        self.assertEqual(data['status'], BrainBuzzSession.STATUS_FINISHED)

    def test_next_is_idempotent_on_index_mismatch(self):
        s = self._active_session('ACTIDM')
        s.current_index = 1
        s.save(update_fields=['current_index'])

        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTIDM'})
        res = _post(c, url, {'action': 'next', 'expected_current_index': 0})
        data = res.json()
        self.assertEqual(data['current_index'], 1)

    def test_end_transitions_to_finished(self):
        s = self._active_session('ACTEND')
        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTEND'})
        res = _post(c, url, {'action': 'end', 'expected_current_index': 0})
        data = res.json()
        self.assertEqual(data['status'], BrainBuzzSession.STATUS_FINISHED)

    def test_403_for_student(self):
        s = self._fresh_session('ACTFOR')
        c = Client()
        c.force_login(self.student)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTFOR'})
        res = _post(c, url, {'action': 'start', 'expected_current_index': None})
        self.assertEqual(res.status_code, 403)

    def test_401_for_anonymous(self):
        s = self._fresh_session('ACTAN1')
        c = Client()
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTAN1'})
        res = _post(c, url, {'action': 'start', 'expected_current_index': None})
        self.assertIn(res.status_code, [302, 401, 403])

    def test_unknown_action_returns_400(self):
        s = self._fresh_session('ACTBAD')
        c = Client()
        c.force_login(self.teacher)
        url = reverse('brainbuzz:api_teacher_action', kwargs={'join_code': 'ACTBAD'})
        res = _post(c, url, {'action': 'launch_rocket', 'expected_current_index': None})
        self.assertEqual(res.status_code, 400)


# ===========================================================================
# api_join
# ===========================================================================

class TestApiJoin(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='bb_teacher_join')

    def test_join_lobby_session_succeeds(self):
        s = _make_session(self.teacher, code='JOINOK')
        c = Client()
        res = _post(c, reverse('brainbuzz:api_join'), {
            'code': 'JOINOK',
            'nickname': 'Alice',
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('participant_id', data)
        self.assertEqual(data['nickname'], 'Alice')
        self.assertIn('redirect_url', data)

    def test_join_nonexistent_code_returns_404(self):
        c = Client()
        res = _post(c, reverse('brainbuzz:api_join'), {
            'code': 'NOTFND',
            'nickname': 'Bob',
        })
        self.assertEqual(res.status_code, 404)

    def test_join_started_session_returns_409(self):
        s = _make_session(self.teacher, code='JSTART', status=BrainBuzzSession.STATUS_ACTIVE)
        c = Client()
        res = _post(c, reverse('brainbuzz:api_join'), {
            'code': 'JSTART',
            'nickname': 'Bob',
        })
        self.assertEqual(res.status_code, 409)

    def test_join_duplicate_nickname_gets_suffix(self):
        s = _make_session(self.teacher, code='JDUPL1')
        _make_participant(s, 'Dave')
        c = Client()
        res = _post(c, reverse('brainbuzz:api_join'), {
            'code': 'JDUPL1',
            'nickname': 'Dave',
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['nickname'], 'Dave #2')

    def test_join_missing_nickname_returns_400(self):
        s = _make_session(self.teacher, code='JMISNN')
        c = Client()
        res = _post(c, reverse('brainbuzz:api_join'), {
            'code': 'JMISNN',
        })
        self.assertEqual(res.status_code, 400)

    def test_rate_limit_blocks_after_10_attempts(self):
        s = _make_session(self.teacher, code='JRATEL')
        c = Client()
        url = reverse('brainbuzz:api_join')
        with patch('brainbuzz.views._check_join_rate_limit', return_value=False):
            res = _post(c, url, {'code': 'JRATEL', 'nickname': 'Zed'})
            self.assertEqual(res.status_code, 429)


# ===========================================================================
# api_submit
# ===========================================================================

class TestApiSubmit(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='bb_teacher_sub')

    def _live_session(self, code):
        s = _make_session(self.teacher, code=code, status=BrainBuzzSession.STATUS_ACTIVE)
        s.current_index = 0
        s.question_deadline = timezone.now() + timedelta(seconds=20)
        s.save(update_fields=['current_index', 'question_deadline'])
        _add_question(s, 0)
        return s

    def test_correct_answer_scores_points(self):
        s = self._live_session('SUBCRR')
        p = _make_participant(s, 'Eve')
        c = Client()
        session = c.session
        session[f'bb_pid_{s.code}'] = p.id
        session.save()

        url = reverse('brainbuzz:api_submit', kwargs={'join_code': s.code})
        res = _post(c, url, {
            'participant_id': p.id,
            'question_index': 0,
            'answer_payload': {'option_label': 'B'},
            'time_taken_ms': 500,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['is_correct'])
        self.assertGreater(data['score_awarded'], 0)

    def test_incorrect_answer_scores_zero(self):
        s = self._live_session('SUBWRG')
        p = _make_participant(s, 'Frank')
        c = Client()
        session = c.session
        session[f'bb_pid_{s.code}'] = p.id
        session.save()

        url = reverse('brainbuzz:api_submit', kwargs={'join_code': s.code})
        res = _post(c, url, {
            'participant_id': p.id,
            'question_index': 0,
            'answer_payload': {'option_label': 'A'},
            'time_taken_ms': 500,
        })
        data = res.json()
        self.assertFalse(data['is_correct'])
        self.assertEqual(data['score_awarded'], 0)

    def test_late_submission_rejected(self):
        s = self._live_session('SUBLAT')
        p = _make_participant(s, 'Grace')
        c = Client()
        session = c.session
        session[f'bb_pid_{s.code}'] = p.id
        session.save()

        s.question_deadline = timezone.now() - timedelta(seconds=5)
        s.save(update_fields=['question_deadline'])

        url = reverse('brainbuzz:api_submit', kwargs={'join_code': s.code})
        res = _post(c, url, {
            'participant_id': p.id,
            'question_index': 0,
            'answer_payload': {'option_label': 'B'},
            'time_taken_ms': 500,
        })
        data = res.json()
        # Answer was correct but submitted past deadline → still marked correct, 0 points
        self.assertTrue(data['is_correct'])
        self.assertEqual(data['score_awarded'], 0)

    def test_duplicate_submission_rejected(self):
        s = self._live_session('SUBDUP')
        p = _make_participant(s, 'Heidi')
        c = Client()
        session = c.session
        session[f'bb_pid_{s.code}'] = p.id
        session.save()

        url = reverse('brainbuzz:api_submit', kwargs={'join_code': s.code})
        payload = {'participant_id': p.id, 'question_index': 0,
                   'answer_payload': {'option_label': 'B'}, 'time_taken_ms': 500}
        _post(c, url, payload)
        res = _post(c, url, payload)
        self.assertEqual(res.status_code, 409)

    def test_wrong_question_index_rejected(self):
        s = self._live_session('SUBIDX')
        p = _make_participant(s, 'Ivan')
        c = Client()
        session = c.session
        session[f'bb_pid_{s.code}'] = p.id
        session.save()

        url = reverse('brainbuzz:api_submit', kwargs={'join_code': s.code})
        res = _post(c, url, {
            'participant_id': p.id,
            'question_index': 99,
            'answer_payload': {'option_label': 'B'},
            'time_taken_ms': 500,
        })
        self.assertEqual(res.status_code, 409)

    def test_not_joined_returns_403(self):
        s = self._live_session('SUBNJ')
        c = Client()
        url = reverse('brainbuzz:api_submit', kwargs={'join_code': s.code})
        res = _post(c, url, {
            'participant_id': 999,
            'question_index': 0,
            'answer_payload': {'option_label': 'B'},
            'time_taken_ms': 500,
        })
        self.assertEqual(res.status_code, 403)


# ===========================================================================
# Role-based access: teacher view visibility
# ===========================================================================

class TestRoleBasedAccess(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='bb_rbac_teacher')
        cls.student = _make_student(username='bb_rbac_student')

    def test_teacher_can_access_create_page(self):
        c = Client()
        c.force_login(self.teacher)
        res = c.get(reverse('brainbuzz:create'))
        self.assertEqual(res.status_code, 200)

    def test_student_cannot_access_create_page(self):
        c = Client()
        c.force_login(self.student)
        res = c.get(reverse('brainbuzz:create'))
        # Redirected away (not a teacher)
        self.assertIn(res.status_code, [302, 200])
        if res.status_code == 200:
            # If 200, must not show session creation form
            self.assertNotIn(b'Create BrainBuzz', res.content)

    def test_anonymous_redirected_from_create(self):
        c = Client()
        res = c.get(reverse('brainbuzz:create'))
        self.assertEqual(res.status_code, 302)

    def test_student_join_page_accessible(self):
        c = Client()
        c.force_login(self.student)
        res = c.get(reverse('brainbuzz:join'))
        self.assertEqual(res.status_code, 200)

    def test_anonymous_join_page_accessible(self):
        c = Client()
        res = c.get(reverse('brainbuzz:join'))
        self.assertEqual(res.status_code, 200)
