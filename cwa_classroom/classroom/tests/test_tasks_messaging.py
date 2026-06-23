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

    @patch('classroom.tasks_messaging.EmailMultiAlternatives')
    def test_send_success_marks_sent(self, MockEmail):
        msg = _make_msg(self.school, frequency='now')
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SENT)
        self.assertIsNone(msg.next_run_at)
        self.assertIsNotNone(msg.last_run_at)

    @patch('classroom.tasks_messaging.EmailMultiAlternatives')
    def test_send_html_attaches_alternative(self, MockEmail):
        instance = MockEmail.return_value
        msg = _make_msg(self.school, frequency='now', body_html='<b>Hi</b>')
        dispatch_message(msg.pk)
        instance.attach_alternative.assert_called_once_with('<b>Hi</b>', 'text/html')

    def test_no_recipients_marks_failed(self):
        msg = _make_msg(
            self.school, frequency='now',
            recipients_to=[], recipients_cc=[], recipients_bcc=[],
        )
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_FAILED)

    @patch('classroom.tasks_messaging.EmailMultiAlternatives')
    def test_email_send_exception_marks_failed(self, MockEmail):
        MockEmail.return_value.send.side_effect = Exception('SMTP error')
        msg = _make_msg(self.school, frequency='now')
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_FAILED)

    @patch('classroom.tasks_messaging.EmailMultiAlternatives')
    def test_weekly_after_send_advances_next_run_at(self, MockEmail):
        msg = _make_msg(
            self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
            next_run_at=_aware(datetime(2026, 6, 22, 9, 0)),
        )
        dispatch_message(msg.pk)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SCHEDULED)
        self.assertIsNotNone(msg.next_run_at)
        self.assertGreater(msg.next_run_at, _aware(datetime(2026, 6, 22, 9, 0)))

    @patch('classroom.tasks_messaging.EmailMultiAlternatives')
    def test_weekly_past_ends_at_marks_sent(self, MockEmail):
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

    @patch('classroom.tasks_messaging.EmailMultiAlternatives')
    def test_bcc_only_recipients_sends(self, MockEmail):
        instance = MockEmail.return_value
        msg = _make_msg(
            self.school, frequency='now',
            recipients_to=[],
            recipients_cc=[],
            recipients_bcc=[{'id': 2, 'name': 'Bob', 'email': 'bob@example.com', 'role': 'staff'}],
        )
        dispatch_message(msg.pk)
        instance.send.assert_called_once()
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessage.STATUS_SENT)


# ---------------------------------------------------------------------------
# check_due_messages
# ---------------------------------------------------------------------------

class TestCheckDueMessages(TestCase):

    def setUp(self):
        self.school = _make_school('check')

    @patch('classroom.tasks_messaging.django_rq')
    def test_enqueues_due_messages(self, mock_rq):
        mock_queue = MagicMock()
        mock_rq.get_queue.return_value = mock_queue

        past = _aware(datetime(2026, 6, 1, 9, 0))
        _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
                  next_run_at=past)
        _make_msg(self.school, frequency='monthly', send_day=1, send_time=time(9, 0),
                  next_run_at=past)

        count = check_due_messages()

        self.assertEqual(count, 2)
        self.assertEqual(mock_queue.enqueue.call_count, 2)

    @patch('classroom.tasks_messaging.django_rq')
    def test_does_not_enqueue_future_messages(self, mock_rq):
        mock_queue = MagicMock()
        mock_rq.get_queue.return_value = mock_queue

        future = timezone.now() + timedelta(hours=1)
        _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
                  next_run_at=future)

        count = check_due_messages()
        self.assertEqual(count, 0)
        mock_queue.enqueue.assert_not_called()

    @patch('classroom.tasks_messaging.django_rq')
    def test_does_not_enqueue_draft_messages(self, mock_rq):
        mock_queue = MagicMock()
        mock_rq.get_queue.return_value = mock_queue

        past = _aware(datetime(2026, 6, 1, 9, 0))
        _make_msg(self.school, frequency='weekly', send_day=1, send_time=time(9, 0),
                  status=ScheduledMessage.STATUS_DRAFT, next_run_at=past)

        count = check_due_messages()
        self.assertEqual(count, 0)

    @patch('classroom.tasks_messaging.django_rq')
    def test_returns_zero_when_nothing_due(self, mock_rq):
        mock_queue = MagicMock()
        mock_rq.get_queue.return_value = mock_queue

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

    @patch('classroom.views_messaging.django_rq')
    def test_frequency_now_enqueues_immediately(self, mock_rq):
        mock_queue = MagicMock()
        mock_rq.get_queue.return_value = mock_queue

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
        mock_queue.enqueue.assert_called_once()

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
