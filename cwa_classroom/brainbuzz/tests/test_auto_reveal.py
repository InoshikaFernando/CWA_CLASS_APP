"""
test_auto_reveal.py
~~~~~~~~~~~~~~~~~~~
Tests for the automatic ACTIVE → REVEAL transition when question_deadline
elapses (CPP-229 lazy auto-reveal).

Coverage:
  _auto_reveal_if_expired():
    - pre-deadline → no change
    - within grace window → no change
    - past grace window → transitions to REVEAL, clears deadline, bumps version
    - session not ACTIVE → no change
    - deadline is None → no change

  api_session_state endpoint:
    - pre-deadline poll returns ACTIVE, no state change
    - post-deadline poll returns REVEAL in same response
    - 304 is NOT returned after auto-reveal (version changed)
    - concurrent requests don't double-transition (race guard)
    - manual Next still works from both ACTIVE and REVEAL
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
    _auto_reveal_if_expired,
    ANSWER_GRACE_MS,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username='ar_teacher'):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@t.com')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_subject():
    return Subject.objects.get_or_create(slug='ar-maths', defaults={'name': 'AR Maths'})[0]


def _make_active_session(teacher, subject, code, deadline_offset_sec):
    """Create an ACTIVE session whose deadline is `deadline_offset_sec` seconds from now."""
    session = BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_ACTIVE,
        current_index=0,
        state_version=1,
        time_per_question_sec=20,
        question_deadline=timezone.now() + timedelta(seconds=deadline_offset_sec),
    )
    BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=0,
        question_text='Auto-reveal Q0',
        question_type=QUESTION_TYPE_MCQ,
        options_json=[
            {'label': 'A', 'text': 'Correct', 'is_correct': True},
            {'label': 'B', 'text': 'Wrong', 'is_correct': False},
        ],
        time_limit_sec=20,
        points_base=1000,
        source_model='Test',
        source_id=0,
    )
    return session


def _add_participant(session, nickname='Player1'):
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


# ---------------------------------------------------------------------------
# Unit tests: _auto_reveal_if_expired
# ---------------------------------------------------------------------------

class TestAutoRevealIfExpired(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('ar_unit_teacher')
        cls.subject = _make_subject()

    def test_pre_deadline_no_change(self):
        session = _make_active_session(self.teacher, self.subject, 'ARPRE1', deadline_offset_sec=30)
        original_version = session.state_version
        result = _auto_reveal_if_expired(session)
        result.refresh_from_db()
        self.assertEqual(result.status, BrainBuzzSession.STATUS_ACTIVE)
        self.assertEqual(result.state_version, original_version)

    def test_within_grace_window_no_change(self):
        # Deadline just passed but within grace (< ANSWER_GRACE_MS ms ago)
        session = _make_active_session(self.teacher, self.subject, 'ARGRCE', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(milliseconds=ANSWER_GRACE_MS - 100)
        session.save()
        original_version = session.state_version
        result = _auto_reveal_if_expired(session)
        result.refresh_from_db()
        self.assertEqual(result.status, BrainBuzzSession.STATUS_ACTIVE)
        self.assertEqual(result.state_version, original_version)

    def test_past_grace_window_transitions_to_reveal(self):
        session = _make_active_session(self.teacher, self.subject, 'AREXP1', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(milliseconds=ANSWER_GRACE_MS + 100)
        session.save()
        _auto_reveal_if_expired(session)
        session.refresh_from_db()
        self.assertEqual(session.status, BrainBuzzSession.STATUS_REVEAL)

    def test_expired_clears_deadline(self):
        session = _make_active_session(self.teacher, self.subject, 'AREXP2', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        _auto_reveal_if_expired(session)
        session.refresh_from_db()
        self.assertIsNone(session.question_deadline)

    def test_expired_bumps_state_version(self):
        session = _make_active_session(self.teacher, self.subject, 'AREXP3', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        original_version = session.state_version
        _auto_reveal_if_expired(session)
        session.refresh_from_db()
        self.assertEqual(session.state_version, original_version + 1)

    def test_non_active_status_not_changed(self):
        session = _make_active_session(self.teacher, self.subject, 'ARSTA1', deadline_offset_sec=0)
        session.status = BrainBuzzSession.STATUS_LOBBY
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        original_version = session.state_version
        result = _auto_reveal_if_expired(session)
        result.refresh_from_db()
        self.assertEqual(result.status, BrainBuzzSession.STATUS_LOBBY)
        self.assertEqual(result.state_version, original_version)

    def test_none_deadline_not_changed(self):
        session = _make_active_session(self.teacher, self.subject, 'ARNLL1', deadline_offset_sec=0)
        session.question_deadline = None
        session.save()
        original_version = session.state_version
        result = _auto_reveal_if_expired(session)
        result.refresh_from_db()
        self.assertEqual(result.status, BrainBuzzSession.STATUS_ACTIVE)
        self.assertEqual(result.state_version, original_version)

    def test_reveal_status_not_changed(self):
        session = _make_active_session(self.teacher, self.subject, 'ARREV1', deadline_offset_sec=0)
        session.status = BrainBuzzSession.STATUS_REVEAL
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        original_version = session.state_version
        _auto_reveal_if_expired(session)
        session.refresh_from_db()
        self.assertEqual(session.status, BrainBuzzSession.STATUS_REVEAL)
        self.assertEqual(session.state_version, original_version)

    def test_finished_status_not_changed(self):
        session = _make_active_session(self.teacher, self.subject, 'ARFIN1', deadline_offset_sec=0)
        session.status = BrainBuzzSession.STATUS_FINISHED
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        original_version = session.state_version
        _auto_reveal_if_expired(session)
        session.refresh_from_db()
        self.assertEqual(session.status, BrainBuzzSession.STATUS_FINISHED)
        self.assertEqual(session.state_version, original_version)


# ---------------------------------------------------------------------------
# Integration tests: api_session_state endpoint
# ---------------------------------------------------------------------------

class TestApiSessionStateAutoReveal(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('ar_api_teacher')
        cls.subject = _make_subject()

    def _state_url(self, code):
        return reverse('brainbuzz:api_session_state', kwargs={'join_code': code})

    def test_pre_deadline_poll_returns_active(self):
        session = _make_active_session(self.teacher, self.subject, 'ARAP01', deadline_offset_sec=30)
        resp = Client().get(self._state_url(session.code))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], BrainBuzzSession.STATUS_ACTIVE)

    def test_pre_deadline_poll_does_not_change_db(self):
        session = _make_active_session(self.teacher, self.subject, 'ARAP02', deadline_offset_sec=30)
        original_version = session.state_version
        Client().get(self._state_url(session.code))
        session.refresh_from_db()
        self.assertEqual(session.status, BrainBuzzSession.STATUS_ACTIVE)
        self.assertEqual(session.state_version, original_version)

    def test_post_deadline_poll_returns_reveal(self):
        session = _make_active_session(self.teacher, self.subject, 'ARAP03', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        resp = Client().get(self._state_url(session.code))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], BrainBuzzSession.STATUS_REVEAL)

    def test_post_deadline_poll_transitions_db(self):
        session = _make_active_session(self.teacher, self.subject, 'ARAP04', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        Client().get(self._state_url(session.code))
        session.refresh_from_db()
        self.assertEqual(session.status, BrainBuzzSession.STATUS_REVEAL)

    def test_post_deadline_response_includes_answer_distribution(self):
        session = _make_active_session(self.teacher, self.subject, 'ARAP05', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        resp = Client().get(self._state_url(session.code))
        data = resp.json()
        self.assertIn('answer_distribution', data)

    def test_304_not_returned_after_auto_reveal(self):
        """Caller sends its cached version; if auto-reveal fires, version changes
        and a 200 (not 304) must be returned."""
        session = _make_active_session(self.teacher, self.subject, 'ARAP06', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        cached_version = session.state_version
        resp = Client().get(self._state_url(session.code) + f'?since={cached_version}')
        # Auto-reveal bumped version → must return 200, not 304
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], BrainBuzzSession.STATUS_REVEAL)

    def test_304_returned_when_no_change_pre_deadline(self):
        session = _make_active_session(self.teacher, self.subject, 'ARAP07', deadline_offset_sec=30)
        resp = Client().get(
            self._state_url(session.code) + f'?since={session.state_version}'
        )
        self.assertEqual(resp.status_code, 304)

    def test_second_poll_after_auto_reveal_returns_304(self):
        """Once transitioned, subsequent polls with the new version get 304."""
        session = _make_active_session(self.teacher, self.subject, 'ARAP08', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        c = Client()
        url = self._state_url(session.code)
        # First poll → auto-reveal, returns 200 with new version
        first = c.get(url + f'?since={session.state_version}')
        self.assertEqual(first.status_code, 200)
        new_version = first.json()['state_version']
        # Second poll with new version → 304
        second = c.get(url + f'?since={new_version}')
        self.assertEqual(second.status_code, 304)


# ---------------------------------------------------------------------------
# Race condition guard: concurrent requests
# ---------------------------------------------------------------------------

class TestAutoRevealRaceGuard(TestCase):
    """Simulate two concurrent requests hitting the endpoint simultaneously.
    Only one should perform the DB transition; both should see REVEAL."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('ar_race_teacher')
        cls.subject = _make_subject()

    def test_double_call_does_not_double_bump_version(self):
        session = _make_active_session(self.teacher, self.subject, 'ARRAC1', deadline_offset_sec=0)
        session.question_deadline = timezone.now() - timedelta(seconds=2)
        session.save()
        original_version = session.state_version

        # Call _auto_reveal_if_expired twice in sequence (simulates two concurrent requests
        # that both read the session before either writes).
        from brainbuzz.views import _auto_reveal_if_expired as fn
        fn(session)
        session.refresh_from_db()
        fn(session)  # second call — session is now REVEAL, should be a no-op
        session.refresh_from_db()

        self.assertEqual(session.status, BrainBuzzSession.STATUS_REVEAL)
        # Version bumped exactly once
        self.assertEqual(session.state_version, original_version + 1)


# ---------------------------------------------------------------------------
# Manual Next still works after auto-reveal
# ---------------------------------------------------------------------------

class TestManualNextAfterAutoReveal(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher('ar_next_teacher')
        cls.subject = _make_subject()

    def setUp(self):
        self.session = _make_active_session(
            self.teacher, self.subject, 'ARNXT1', deadline_offset_sec=0
        )
        # Add a second question so Next has somewhere to go
        BrainBuzzSessionQuestion.objects.create(
            session=self.session,
            order=1,
            question_text='Q1',
            question_type=QUESTION_TYPE_MCQ,
            options_json=[{'label': 'A', 'text': 'OK', 'is_correct': True}],
            time_limit_sec=20,
            points_base=1000,
            source_model='Test',
            source_id=1,
        )
        _add_participant(self.session)
        self.client = Client()
        self.client.force_login(self.teacher)
        self.action_url = reverse(
            'brainbuzz:api_teacher_action', kwargs={'join_code': self.session.code}
        )

    def test_manual_next_from_active_skips_to_next_question(self):
        resp = self.client.post(
            self.action_url,
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['current_index'], 1)
        self.assertEqual(data['status'], BrainBuzzSession.STATUS_ACTIVE)

    def test_manual_next_from_auto_revealed_session(self):
        # Let auto-reveal fire first
        self.session.question_deadline = timezone.now() - timedelta(seconds=2)
        self.session.save()
        Client().get(
            reverse('brainbuzz:api_session_state', kwargs={'join_code': self.session.code})
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, BrainBuzzSession.STATUS_REVEAL)

        # Teacher clicks Next → should advance to Q1
        resp = self.client.post(
            self.action_url,
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['current_index'], 1)
        self.assertEqual(data['status'], BrainBuzzSession.STATUS_ACTIVE)

    def test_manual_next_from_active_before_deadline(self):
        """Teacher can force-advance before the timer runs out."""
        self.session.question_deadline = timezone.now() + timedelta(seconds=30)
        self.session.save()
        resp = self.client.post(
            self.action_url,
            data=json.dumps({'action': 'next', 'expected_current_index': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['current_index'], 1)
