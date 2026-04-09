"""Tests for student dashboard recent activity ordering and time tracking.

Covers:
  - recent_activity is a single merged list sorted by completed_at descending
    (not grouped by quiz type)
  - time_daily/time_weekly on all three student pages sums quiz-record time:
      StudentFinalAnswer, BasicFactsResult, PuzzleSession, HomeworkSubmission
  - /student-dashboard/, /hub/, and /maths/ all show the same time
  - Heartbeat (TimeLog) does NOT affect any of these pages
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import ClassRoom
from homework.models import Homework, HomeworkSubmission
from maths.models import BasicFactsResult, StudentFinalAnswer, TimeLog
from number_puzzles.models import NumberPuzzleLevel, PuzzleSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, email=None):
    email = email or f'wlhtestmails+{username}@gmail.com'
    user = CustomUser.objects.create_user(
        username, email, 'password1!',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'},
    )
    user.roles.add(role)
    return user


def _bf(student, *, seconds=60, offset_seconds=0, tag=''):
    """Create a BasicFactsResult completed `offset_seconds` ago."""
    r = BasicFactsResult.objects.create(
        student=student,
        subtopic='Addition',
        level_number=1,
        session_id=f'sess-{tag}-{offset_seconds}',
        score=5,
        total_points=10,
        time_taken_seconds=seconds,
        points=50,
    )
    ts = timezone.now() - timedelta(seconds=offset_seconds)
    BasicFactsResult.objects.filter(pk=r.pk).update(completed_at=ts)
    r.refresh_from_db()
    return r


def _puzzle_session(student, *, duration_seconds=90, offset_seconds=0):
    """Create a completed PuzzleSession."""
    level, _ = NumberPuzzleLevel.objects.get_or_create(
        number=999,
        defaults={
            'name': 'Test Level',
            'slug': 'test-level-999',
            'operators_allowed': '+',
        },
    )
    session = PuzzleSession.objects.create(
        student=student,
        level=level,
        status='completed',
        score=8,
        total_questions=10,
        duration_seconds=duration_seconds,
    )
    ts = timezone.now() - timedelta(seconds=offset_seconds)
    PuzzleSession.objects.filter(pk=session.pk).update(completed_at=ts)
    session.refresh_from_db()
    return session


def _homework_submission(student, *, seconds=120):
    """Create a HomeworkSubmission for today."""
    classroom = ClassRoom.objects.create(name='Test Class HW')
    homework = Homework.objects.create(
        classroom=classroom,
        title='Test Homework',
        due_date=timezone.now() + timedelta(days=7),
        num_questions=5,
    )
    return HomeworkSubmission.objects.create(
        homework=homework,
        student=student,
        score=4,
        total_questions=5,
        time_taken_seconds=seconds,
        attempt_number=1,
    )


def _heartbeat(client, seconds=30):
    """Send a heartbeat to accumulate TimeLog time."""
    return client.post(
        '/api/update-time-log/',
        data=json.dumps({'seconds': seconds}),
        content_type='application/json',
    )


# ---------------------------------------------------------------------------
# Recent Activity — ordering
# ---------------------------------------------------------------------------

class RecentActivityOrderTest(TestCase):
    """recent_activity context must be a single list sorted newest-first.

    Regression: previously items were grouped by quiz type (all topic quizzes,
    then all basic facts, etc.) — this test ensures they are interleaved by time.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = _make_student('actorder_student')

    def setUp(self):
        self.client.login(username='actorder_student', password='password1!')

    def tearDown(self):
        BasicFactsResult.objects.filter(student=self.student).delete()

    def test_sorted_newest_first(self):
        _bf(self.student, offset_seconds=200, tag='old')
        _bf(self.student, offset_seconds=100, tag='mid')
        _bf(self.student, offset_seconds=10, tag='new')

        resp = self.client.get(reverse('student_dashboard'))
        self.assertEqual(resp.status_code, 200)

        times = [item['completed_at'] for item in resp.context['recent_activity']]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_is_single_merged_list_not_grouped(self):
        """Items from different quiz types must be interleaved by time."""
        # basic-facts 300s ago, puzzle 50s ago — puzzle must appear first
        _bf(self.student, offset_seconds=300, tag='group-a')
        _puzzle_session(self.student, offset_seconds=50)

        resp = self.client.get(reverse('student_dashboard'))
        activity = resp.context['recent_activity']

        self.assertIsInstance(activity, list)
        times = [item['completed_at'] for item in activity]
        self.assertEqual(times, sorted(times, reverse=True),
                         'Activity must be sorted by time, not grouped by type')

    def test_activity_items_have_required_keys(self):
        _bf(self.student, tag='keys')

        resp = self.client.get(reverse('student_dashboard'))
        item = resp.context['recent_activity'][0]

        for key in ('completed_at', 'name', 'score_label', 'pct'):
            self.assertIn(key, item)

    def tearDown(self):
        BasicFactsResult.objects.filter(student=self.student).delete()
        PuzzleSession.objects.filter(student=self.student).delete()


# ---------------------------------------------------------------------------
# Time tracking — shared helper
# ---------------------------------------------------------------------------

def _assert_time_equals(test_case, url, expected_minutes, *, url_name=None):
    """GET `url`, assert time_daily == '{expected_minutes}m'."""
    resp = test_case.client.get(url)
    test_case.assertIn(resp.status_code, [200])
    test_case.assertEqual(
        resp.context['time_daily'],
        f'{expected_minutes}m',
        f'{url} showed wrong time_daily',
    )


# ---------------------------------------------------------------------------
# Dashboard Time — /student-dashboard/
# ---------------------------------------------------------------------------

class DashboardTimeTest(TestCase):
    """time_daily on /student-dashboard/ sums quiz-record time only."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _make_student('dashtime_student')

    def setUp(self):
        self.client.login(username='dashtime_student', password='password1!')

    def _daily(self):
        resp = self.client.get(reverse('student_dashboard'))
        self.assertEqual(resp.status_code, 200)
        return resp.context['time_daily']

    def test_no_records_shows_zero(self):
        self.assertEqual(self._daily(), '0m')

    def test_basic_facts_counted(self):
        _bf(self.student, seconds=120, tag='dashbf')
        self.assertEqual(self._daily(), '2m')

    def test_puzzle_session_counted(self):
        _puzzle_session(self.student, duration_seconds=180)
        self.assertEqual(self._daily(), '3m')

    def test_homework_counted(self):
        _homework_submission(self.student, seconds=150)
        self.assertEqual(self._daily(), '2m')

    def test_all_sources_accumulate(self):
        """60s bf + 60s puzzle + 60s hw = 180s = 3m."""
        _bf(self.student, seconds=60, tag='acc')
        _puzzle_session(self.student, duration_seconds=60)
        _homework_submission(self.student, seconds=60)
        self.assertEqual(self._daily(), '3m')

    def test_heartbeat_does_not_affect_dashboard_time(self):
        """Critical: heartbeat accumulates TimeLog but dashboard must ignore it."""
        _heartbeat(self.client, seconds=3600)  # 1 hour via heartbeat

        # No quiz records → still 0m
        self.assertEqual(self._daily(), '0m')

    def tearDown(self):
        BasicFactsResult.objects.filter(student=self.student).delete()
        PuzzleSession.objects.filter(student=self.student).delete()
        HomeworkSubmission.objects.filter(student=self.student).delete()
        ClassRoom.objects.filter(name='Test Class HW').delete()


# ---------------------------------------------------------------------------
# Hub Time — /hub/
# ---------------------------------------------------------------------------

class HubTimeTest(TestCase):
    """time_daily on /hub/ must reflect quiz records, not heartbeat time."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _make_student('hubtime_student')

    def setUp(self):
        self.client.login(username='hubtime_student', password='password1!')

    def _hub_resp(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_no_records_shows_zero(self):
        self.assertEqual(self._hub_resp().context['time_daily'], '0m')

    def test_basic_facts_counted(self):
        _bf(self.student, seconds=120, tag='hubbf')
        self.assertEqual(self._hub_resp().context['time_daily'], '2m')

    def test_heartbeat_does_not_affect_hub_time(self):
        """Heartbeat must not inflate hub time."""
        _heartbeat(self.client, seconds=3600)
        self.assertEqual(self._hub_resp().context['time_daily'], '0m')

    def test_hub_matches_dashboard(self):
        """Hub and dashboard must show identical time_daily."""
        _bf(self.student, seconds=120, tag='match')

        hub = self.client.get(reverse('subjects_hub'))
        dash = self.client.get(reverse('student_dashboard'))

        self.assertEqual(hub.status_code, 200)
        self.assertEqual(dash.status_code, 200)
        self.assertEqual(hub.context['time_daily'], dash.context['time_daily'])

    def tearDown(self):
        BasicFactsResult.objects.filter(student=self.student).delete()


# ---------------------------------------------------------------------------
# Maths Time — /maths/
# ---------------------------------------------------------------------------

class MathsTimeTest(TestCase):
    """time_daily on /maths/ must reflect quiz records, not heartbeat time."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _make_student('mathstime_student')

    def setUp(self):
        self.client.login(username='mathstime_student', password='password1!')

    def _maths_resp(self):
        resp = self.client.get('/maths/')
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_no_records_shows_zero(self):
        self.assertEqual(self._maths_resp().context['time_daily'], '0m')

    def test_basic_facts_counted(self):
        _bf(self.student, seconds=120, tag='mathsbf')
        self.assertEqual(self._maths_resp().context['time_daily'], '2m')

    def test_heartbeat_does_not_affect_maths_time(self):
        """Heartbeat must not inflate /maths/ time."""
        _heartbeat(self.client, seconds=3600)
        self.assertEqual(self._maths_resp().context['time_daily'], '0m')

    def test_maths_matches_dashboard(self):
        """Maths page and dashboard must show identical time_daily."""
        _bf(self.student, seconds=120, tag='mathsmatch')

        maths = self.client.get('/maths/')
        dash = self.client.get(reverse('student_dashboard'))

        self.assertEqual(maths.status_code, 200)
        self.assertEqual(dash.status_code, 200)
        self.assertEqual(maths.context['time_daily'], dash.context['time_daily'])

    def tearDown(self):
        BasicFactsResult.objects.filter(student=self.student).delete()


# ---------------------------------------------------------------------------
# Cross-page consistency
# ---------------------------------------------------------------------------

class AllPagesTimeConsistencyTest(TestCase):
    """Dashboard, hub, and maths all show the same time_daily."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _make_student('allpages_student')

    def setUp(self):
        self.client.login(username='allpages_student', password='password1!')
        _bf(self.student, seconds=180, tag='consistent')

    def tearDown(self):
        BasicFactsResult.objects.filter(student=self.student).delete()

    def test_all_three_pages_show_same_time(self):
        dash = self.client.get(reverse('student_dashboard'))
        hub = self.client.get(reverse('subjects_hub'))
        maths = self.client.get('/maths/')

        self.assertEqual(dash.status_code, 200)
        self.assertEqual(hub.status_code, 200)
        self.assertEqual(maths.status_code, 200)

        self.assertEqual(dash.context['time_daily'], '3m')
        self.assertEqual(hub.context['time_daily'], dash.context['time_daily'])
        self.assertEqual(maths.context['time_daily'], dash.context['time_daily'])
