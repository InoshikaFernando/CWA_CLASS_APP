"""Tests for student time tracking (TimeLog).

The heartbeat system (UpdateTimeLogView) is the source of truth for time
spent on the platform.  Dashboard views and quiz completion must NEVER
overwrite heartbeat-accumulated time.
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.utils.timezone import localtime

from accounts.models import CustomUser, Role
from maths.models import TimeLog
from maths.views import get_or_create_time_log


def _make_student(username='timestudent', email='wlhtestmails+time@gmail.com'):
    """Create a student user with the student role."""
    user = CustomUser.objects.create_user(username, email, 'password1!')
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'},
    )
    user.roles.add(role)
    return user


class TimeLogModelTest(TestCase):
    """Tests for TimeLog creation and daily/weekly resets."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _make_student()

    def test_get_or_create_time_log_creates_record(self):
        time_log = get_or_create_time_log(self.student)
        self.assertIsNotNone(time_log)
        self.assertEqual(time_log.daily_total_seconds, 0)
        self.assertEqual(time_log.weekly_total_seconds, 0)

    def test_get_or_create_returns_same_record(self):
        tl1 = get_or_create_time_log(self.student)
        tl2 = get_or_create_time_log(self.student)
        self.assertEqual(tl1.pk, tl2.pk)

    def test_daily_reset_zeroes_daily_time(self):
        time_log = get_or_create_time_log(self.student)
        time_log.daily_total_seconds = 500
        # Simulate that last_reset_date was yesterday
        yesterday = (localtime(timezone.now()) - timedelta(days=1)).date()
        TimeLog.objects.filter(pk=time_log.pk).update(
            daily_total_seconds=500, last_reset_date=yesterday,
        )
        time_log.refresh_from_db()
        time_log.reset_daily_if_needed()
        time_log.refresh_from_db()
        self.assertEqual(time_log.daily_total_seconds, 0)

    def test_weekly_reset_zeroes_weekly_time(self):
        time_log = get_or_create_time_log(self.student)
        time_log.weekly_total_seconds = 3000
        # Set last_reset_week to a different week number
        now_local = localtime(timezone.now())
        old_week = now_local.isocalendar()[1] - 1  # previous week
        TimeLog.objects.filter(pk=time_log.pk).update(
            weekly_total_seconds=3000, last_reset_week=old_week,
        )
        time_log.refresh_from_db()
        time_log.reset_weekly_if_needed()
        time_log.refresh_from_db()
        self.assertEqual(time_log.weekly_total_seconds, 0)

    def test_no_reset_when_same_day(self):
        time_log = get_or_create_time_log(self.student)
        time_log.daily_total_seconds = 500
        time_log.save(update_fields=['daily_total_seconds'])
        time_log.reset_daily_if_needed()
        time_log.refresh_from_db()
        self.assertEqual(time_log.daily_total_seconds, 500)


class HeartbeatViewTest(TestCase):
    """Tests for the UpdateTimeLogView (heartbeat API)."""

    def setUp(self):
        self.student = _make_student('hbstudent', 'wlhtestmails+hb@gmail.com')
        self.client.login(username='hbstudent', password='password1!')

    def _heartbeat(self, seconds=30):
        """Send a single heartbeat."""
        return self.client.post(
            '/api/update-time-log/',
            data=json.dumps({'seconds': seconds}),
            content_type='application/json',
        )

    def test_heartbeat_increments_time(self):
        resp = self._heartbeat()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['daily_seconds'], 30)
        self.assertEqual(data['weekly_seconds'], 30)

    def test_multiple_heartbeats_accumulate(self):
        for _ in range(3):
            self._heartbeat()
        tl = TimeLog.objects.get(student=self.student)
        self.assertEqual(tl.daily_total_seconds, 90)
        self.assertEqual(tl.weekly_total_seconds, 90)

    def test_heartbeat_time_survives_dashboard_load(self):
        """Critical regression test: loading the dashboard must NOT reset
        heartbeat-accumulated time back to zero."""
        # Accumulate 90 seconds via heartbeat
        for _ in range(3):
            self._heartbeat()

        # Load the student dashboard (classroom)
        resp = self.client.get('/student-dashboard/')
        self.assertEqual(resp.status_code, 200)

        # Time must still be 90s, NOT reset to 0
        tl = TimeLog.objects.get(student=self.student)
        self.assertEqual(tl.daily_total_seconds, 90)
        self.assertEqual(tl.weekly_total_seconds, 90)

    def test_heartbeat_time_survives_maths_ajax(self):
        """The maths AJAX time endpoint must NOT overwrite heartbeat time."""
        # Accumulate time
        for _ in range(2):
            self._heartbeat()

        # Hit the maths time endpoint
        resp = self.client.get('/maths/api/update-time-log/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['daily_seconds'], 60)
        self.assertEqual(data['weekly_seconds'], 60)

        # DB should still have the accumulated time
        tl = TimeLog.objects.get(student=self.student)
        self.assertEqual(tl.daily_total_seconds, 60)
