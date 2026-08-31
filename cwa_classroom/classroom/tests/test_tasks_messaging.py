"""
Unit tests for classroom/tasks_messaging.py (CPP-353).

Coverage:
  - compute_next_run_at: all frequency branches + edge cases
  - dispatch_message: send success, no recipients, email failure, recurring reschedule
  - check_due_messages: enqueues due messages only
  - view integration: _enqueue_or_schedule called on non-draft post
"""
import json
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from classroom.models import ScheduledMessage, School
from classroom.tasks_messaging import (
    _add_months,
    _in_range,
    check_due_messages,
    compute_next_run_at,
    dispatch_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_school(suffix='353'):
    return School.objects.create(name=f'Test School {suffix}', is_active=True)


def _make_msg(school, **kwargs):
    defaults = dict(
        subject='Hello',
        body_html='<p>Hello</p>',
        recipients_to=[{'id': 1, 'name': 'Alice', 'email': 'alice@example.com', 'role': 'student'}],
        frequency='now',
        status=ScheduledMessage.STATUS_SCHEDULED,
    )
    defaults.update(kwargs)
    return ScheduledMessage.objects.create(school=school, **defaults)


def _aware(dt):
    return timezone.make_aware(dt)


# ---------------------------------------------------------------------------
# compute_next_run_at
# ---------------------------------------------------------------------------

class TestComputeNextRunAt(TestCase):

    def setUp(self):
        self.school = _make_school()

    def test_frequency_now_returns_none(self):
        msg = _make_msg(self.school, frequency='now')
        self.assertIsNone(compute_next_run_at(msg))

    def test_frequency_once_returns_scheduled_at(self):
        when = _aware(datetime(2026, 8, 1, 9, 0))
        msg = _make_msg(self.school, frequency='once', scheduled_at=when)
        self.assertEqual(compute_next_run_at(msg), when)

    def test_frequency_once_returns_none_when_no_scheduled_at(self):
        msg = _make_msg(self.school, frequency='once', scheduled_at=None)
        self.assertIsNone(compute_next_run_at(msg))

    def test_weekly_returns_next_correct_weekday(self):
        # send_day=1 (Monday); from_dt is a Tuesday → next Monday
        msg = _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0))
        from_dt = _aware(datetime(2026, 6, 23, 10, 0))  # Tuesday
        result = compute_next_run_at(msg, from_dt=from_dt)
        self.assertEqual(result.date(), date(2026, 6, 29))
        self.assertEqual(result.time().hour, 9)

    def test_weekly_same_weekday_time_past_returns_next_week(self):
        # send_day=1 (Monday) at 09:00; from_dt is Monday at 10:00 → next Monday
        msg = _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0))
        from_dt = _aware(datetime(2026, 6, 22, 10, 0))  # Monday
        result = compute_next_run_at(msg, from_dt=from_dt)
        self.assertEqual(result.date(), date(2026, 6, 29))

    def test_weekly_same_weekday_time_future_returns_today(self):
        # send_day=1 (Monday) at 15:00; from_dt is Monday at 10:00 → today
        msg = _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(15, 0))
        from_dt = _aware(datetime(2026, 6, 22, 10, 0))  # Monday
        result = compute_next_run_at(msg, from_dt=from_dt)
        self.assertEqual(result.date(), date(2026, 6, 22))

    def test_weekly_missing_send_day_returns_none(self):
        msg = _make_msg(self.school, frequency='weekly', send_day=None, send_time=time(9, 0))
        self.assertIsNone(compute_next_run_at(msg))

    def test_weekly_missing_send_time_returns_none(self):
        msg = _make_msg(self.school, frequency='weekly', send_day=1, send_time=None)
        self.assertIsNone(compute_next_run_at(msg))

    def test_weekly_outside_ends_at_returns_none(self):
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            ends_at=date(2026, 6, 21),
        )
        from_dt = _aware(datetime(2026, 6, 22, 10, 0))
        self.assertIsNone(compute_next_run_at(msg, from_dt=from_dt))

    def test_monthly_returns_next_occurrence_same_month(self):
        msg = _make_msg(self.school, frequency='monthly', send_day=28, send_time=time(9, 0))
        from_dt = _aware(datetime(2026, 6, 1, 10, 0))
        result = compute_next_run_at(msg, from_dt=from_dt)
        self.assertEqual(result.date(), date(2026, 6, 28))

    def test_monthly_returns_next_month_when_day_past(self):
        msg = _make_msg(self.school, frequency='monthly', send_day=1, send_time=time(9, 0))
        from_dt = _aware(datetime(2026, 6, 5, 10, 0))
        result = compute_next_run_at(msg, from_dt=from_dt)
        self.assertEqual(result.date(), date(2026, 7, 1))

    def test_monthly_skips_invalid_day_for_short_month(self):
        # send_day=31 with from in April → skip April, use May 31
        msg = _make_msg(self.school, frequency='monthly', send_day=31, send_time=time(9, 0))
        from_dt = _aware(datetime(2026, 4, 1, 10, 0))
        result = compute_next_run_at(msg, from_dt=from_dt)
        self.assertEqual(result.date(), date(2026, 5, 31))

    def test_monthly_missing_send_day_returns_none(self):
        msg = _make_msg(self.school, frequency='monthly', send_day=None, send_time=time(9, 0))
        self.assertIsNone(compute_next_run_at(msg))

    def test_monthly_outside_ends_at_returns_none(self):
        msg = _make_msg(
            self.school, frequency='monthly', send_day=1, send_time=time(9, 0),
            ends_at=date(2026, 5, 31),
        )
        from_dt = _aware(datetime(2026, 6, 5, 10, 0))
        self.assertIsNone(compute_next_run_at(msg, from_dt=from_dt))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers(TestCase):

    def test_in_range_no_bounds(self):
        msg = MagicMock(starts_at=None, ends_at=None)
        self.assertTrue(_in_range(date(2026, 6, 15), msg))

    def test_in_range_before_starts(self):
        msg = MagicMock(starts_at=date(2026, 7, 1), ends_at=None)
        self.assertFalse(_in_range(date(2026, 6, 15), msg))

    def test_in_range_after_ends(self):
        msg = MagicMock(starts_at=None, ends_at=date(2026, 6, 14))
        self.assertFalse(_in_range(date(2026, 6, 15), msg))

    def test_in_range_on_boundary(self):
        msg = MagicMock(starts_at=date(2026, 6, 15), ends_at=date(2026, 6, 15))
        self.assertTrue(_in_range(date(2026, 6, 15), msg))

    def test_add_months_simple(self):
        self.assertEqual(_add_months(2026, 6, 1), (2026, 7))

    def test_add_months_year_rollover(self):
        self.assertEqual(_add_months(2026, 12, 1), (2027, 1))


# ---------------------------------------------------------------------------
# dispatch_message
# ---------------------------------------------------------------------------

class TestDispatchMessage(TestCase):

    def setUp(self):
        self.school = _make_school('dispatch')

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_send_success_marks_sent(self, mock_send):
        msg = _make_msg(self.school, frequency='now')
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SENT)
        self.assertIsNone(msg.next_run_at)
        self.assertIsNotNone(msg.last_run_at)
        mock_send.assert_called_once()

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_send_passes_html_body(self, mock_send):
        """HTML body is forwarded as html_content to send_prebuilt_email."""
        msg = _make_msg(self.school, frequency='now', body_html='<b>Hi</b>')
        dispatch_message(msg.pk)
        pos, _ = mock_send.call_args
        self.assertEqual(pos[2], '<b>Hi</b>')

    def test_no_recipients_marks_failed(self):
        msg = _make_msg(
            self.school, frequency='now',
            recipients_to=[], recipients_cc=[], recipients_bcc=[],
        )
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_FAILED)

    @patch('classroom.email_service.send_prebuilt_email', return_value=False)
    def test_send_failure_does_not_revert_status(self, mock_send):
        """send_prebuilt_email returning False (SMTP error) does not revert
        message to FAILED — status stays SENT; EmailQueue handles retry."""
        msg = _make_msg(self.school, frequency='now')
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SENT)

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_weekly_after_send_advances_next_run_at(self, mock_send):
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            next_run_at=_aware(datetime(2026, 6, 22, 9, 0)),
        )
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SCHEDULED)
        self.assertIsNotNone(msg.next_run_at)
        self.assertGreater(msg.next_run_at, _aware(datetime(2026, 6, 22, 9, 0)))

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_weekly_past_ends_at_marks_sent(self, mock_send):
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            ends_at=date(2026, 6, 22),
            next_run_at=_aware(datetime(2026, 6, 22, 9, 0)),
        )
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SENT)
        self.assertIsNone(msg.next_run_at)

    def test_nonexistent_msg_id_does_not_raise(self):
        dispatch_message(999999)

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_bcc_only_recipients_sends(self, mock_send):
        msg = _make_msg(
            self.school, frequency='now',
            recipients_to=[],
            recipients_cc=[],
            recipients_bcc=[{'id': 2, 'name': 'Bob', 'email': 'bob@example.com', 'role': 'staff'}],
        )
        dispatch_message(msg.pk)
        mock_send.assert_called_once()
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SENT)


# ---------------------------------------------------------------------------
# check_due_messages
# ---------------------------------------------------------------------------

class TestCheckDueMessages(TestCase):

    def setUp(self):
        self.school = _make_school('check')

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_dispatches_due_messages(self, mock_send):
        """check_due_messages dispatches all SCHEDULED messages with past next_run_at."""
        past = _aware(datetime(2026, 6, 1, 9, 0))
        _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
                  next_run_at=past)
        _make_msg(self.school, frequency='monthly', send_day=1, send_time=time(9, 0),
                  next_run_at=past)
        count = check_due_messages()
        self.assertEqual(count, 2)

    @patch('classroom.email_service.send_prebuilt_email', return_value=True)
    def test_does_not_dispatch_future_messages(self, mock_send):
        future = timezone.now() + timedelta(hours=1)
        _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
                  next_run_at=future)
        count = check_due_messages()
        self.assertEqual(count, 0)
        mock_send.assert_not_called()

    def test_does_not_dispatch_draft_messages(self):
        past = _aware(datetime(2026, 6, 1, 9, 0))
        _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
                  status=ScheduledMessage.STATUS_DRAFT, next_run_at=past)
        count = check_due_messages()
        self.assertEqual(count, 0)

    def test_returns_zero_when_nothing_due(self):
        count = check_due_messages()
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# View integration — _enqueue_or_schedule called on post
# ---------------------------------------------------------------------------

class TestViewEnqueuesOnPost(TestCase):
    """Verifies that posting frequency='now' triggers immediate enqueue."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.school = _make_school('viewint')
        self.user = User.objects.create_user(
            username='admin_353', password='pw', email='admin353@test.com',
        )
        self.user.role = Role.ADMIN
        self.user.save()
        self.school.admin = self.user
        self.school.save()

    @patch('classroom.tasks_messaging.dispatch_message')
    def test_frequency_now_enqueues_immediately(self, mock_dispatch):
        self.client.force_login(self.user)
        self.client.post('/admin-dashboard/messaging/compose/', {
            'action': 'send',
            'subject': 'Test',
            'body': '<p>Hi</p>',
            'frequency': 'now',
            'recipients_to': json.dumps([{'id': 1, 'name': 'A', 'email': 'a@b.com', 'role': 'staff'}]),
            'recipients_cc': '[]',
            'recipients_bcc': '[]',
        })
        mock_dispatch.assert_called_once()

    @patch('classroom.views_messaging._enqueue_or_schedule')
    def test_draft_does_not_enqueue(self, mock_enqueue):
        self.client.force_login(self.user)
        self.client.post('/admin-dashboard/messaging/compose/', {
            'action': 'draft',
            'subject': 'Draft msg',
            'body': '<p>Hi</p>',
            'frequency': 'now',
            'recipients_to': '[]',
            'recipients_cc': '[]',
            'recipients_bcc': '[]',
        })
        mock_enqueue.assert_not_called()

    @patch('classroom.views_messaging._enqueue_or_schedule')
    def test_scheduled_once_calls_enqueue_or_schedule(self, mock_enqueue):
        self.client.force_login(self.user)
        self.client.post('/admin-dashboard/messaging/compose/', {
            'action': 'send',
            'subject': 'Scheduled',
            'body': '<p>Hi</p>',
            'frequency': 'once',
            'schedule_date': '2026-09-01',
            'schedule_time': '09:00',
            'recipients_to': json.dumps([{'id': 1, 'name': 'A', 'email': 'a@b.com', 'role': 'staff'}]),
            'recipients_cc': '[]',
            'recipients_bcc': '[]',
        })
        mock_enqueue.assert_called_once()
        sm = mock_enqueue.call_args[0][0]
        self.assertEqual(sm.frequency, 'once')


class TestWeeklyStartDateInTheFuture(TestCase):
    """A weekly message starting later could not be scheduled at all.

    compute_next_run_at took the next matching weekday from TODAY, found it sat
    before starts_at, and returned None. _enqueue_or_schedule turns None into a
    ValueError, which the teacher reads as "Message could not be queued —
    please try again" — and retrying never fixes it, because tomorrow's answer
    is the same.

    Falling outside the range means "look further ahead", not "impossible".
    Only ends_at can genuinely rule a message out, and it still does.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = _make_school()

    def test_a_start_date_later_this_week_schedules_after_it(self):
        # Monday 09:00 weekly, asked for on Monday, starting Tuesday: the run
        # is the FOLLOWING Monday, not nothing at all.
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            starts_at=date(2026, 9, 1),
        )
        from_dt = _aware(datetime(2026, 8, 31, 10, 0))  # Monday

        result = compute_next_run_at(msg, from_dt=from_dt)

        self.assertIsNotNone(result, 'a future start date must not be unschedulable')
        self.assertEqual(result.date(), date(2026, 9, 7))
        self.assertEqual(result.time().hour, 9)

    def test_a_start_date_months_out_still_schedules(self):
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            starts_at=date(2027, 3, 1),
        )
        from_dt = _aware(datetime(2026, 8, 31, 10, 0))

        result = compute_next_run_at(msg, from_dt=from_dt)

        self.assertIsNotNone(result)
        # 1 Mar 2027 is itself a Monday, so it is the first valid run.
        self.assertEqual(result.date(), date(2027, 3, 1))

    def test_a_start_date_on_the_send_day_runs_that_day(self):
        """The time of day cannot have "already passed" on a future date."""
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            starts_at=date(2026, 9, 7),
        )
        from_dt = _aware(datetime(2026, 8, 31, 23, 0))

        result = compute_next_run_at(msg, from_dt=from_dt)

        self.assertEqual(result.date(), date(2026, 9, 7))

    def test_an_end_date_in_the_past_still_returns_none(self):
        """The guard that must survive: past ends_at genuinely means never."""
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            ends_at=date(2026, 6, 21),
        )
        from_dt = _aware(datetime(2026, 6, 22, 10, 0))

        self.assertIsNone(compute_next_run_at(msg, from_dt=from_dt))


class TestWeeklyReadsTheClockInLocalTime(TestCase):
    """The weekday and the hour must be read in the school's zone.

    "Every Monday at 09:00" means 09:00 where the school is. The calculation
    read them off ``now``, which is UTC whenever no from_dt is passed, and then
    wrote the answer back through make_aware() as LOCAL time — so the two
    halves disagreed by the UTC offset, and near midnight by a whole day.

    Every existing test passes a local-aware from_dt, which is why none of them
    saw it: only production took the tz.now() path.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = _make_school()

    def test_the_answer_is_the_same_however_the_instant_is_expressed(self):
        """UTC and local spellings of one moment must schedule identically."""
        from datetime import timezone as dt_timezone

        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
        )
        local = _aware(datetime(2026, 8, 31, 10, 0))          # Monday, local
        same_instant_utc = local.astimezone(dt_timezone.utc)  # same moment

        self.assertEqual(
            compute_next_run_at(msg, from_dt=local),
            compute_next_run_at(msg, from_dt=same_instant_utc),
        )

    def test_it_holds_across_the_utc_date_boundary(self):
        """The case that moved the weekday by a day, not just the hour."""
        from datetime import timezone as dt_timezone

        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
        )
        # Local Monday morning is still Sunday in UTC.
        local = _aware(datetime(2026, 8, 31, 8, 0))
        same_instant_utc = local.astimezone(dt_timezone.utc)

        self.assertEqual(
            compute_next_run_at(msg, from_dt=local),
            compute_next_run_at(msg, from_dt=same_instant_utc),
        )
        # 09:00 local has not passed at 08:00 local, so it runs today.
        self.assertEqual(
            compute_next_run_at(msg, from_dt=local).date(), date(2026, 8, 31),
        )


class TestTheReportedFailure(TestCase):
    """The exact shape that reached a teacher, reproduced.

    The two defects are entangled, and neither alone explains it. Reading the
    clock in UTC is what made TODAY the candidate weekday — a local from_dt at
    10:00 would have rolled to next week and quietly worked — and today then
    fell before starts_at, so the range check returned None and the compose
    page said "Message could not be queued — please try again".

    That is why the existing suite was green while the feature was broken:
    every test passed a local-aware from_dt, so none of them took the path
    production takes.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = _make_school()

    def test_a_weekly_message_starting_tomorrow_can_be_scheduled(self):
        from datetime import timezone as dt_timezone

        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            starts_at=date(2026, 9, 1),
        )
        # 05:56 UTC on Monday 31 Aug — the instant the CI run failed at, and
        # the same moment as 17:56 local.
        from_dt = datetime(2026, 8, 31, 5, 56, tzinfo=dt_timezone.utc)

        result = compute_next_run_at(msg, from_dt=from_dt)

        self.assertIsNotNone(
            result, 'this returned None, and the teacher was told to try again',
        )
        self.assertEqual(result.date(), date(2026, 9, 7))
