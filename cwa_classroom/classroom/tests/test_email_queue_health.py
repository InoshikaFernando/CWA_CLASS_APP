"""
Tests for the email-queue watchdog: health classification, the alert command,
and the deep health endpoint's non-fatal warning.

These exist because a stalled drain was invisible for ten weeks in 2026 —
invoices read as issued while 316 emails sat queued. Each surface below is one
of the ways that is now meant to be caught.
"""
import json

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.test import TestCase, Client
from django.utils import timezone
from unittest.mock import patch

from classroom.email_health import (
    DEPTH_WARN, STALE_CRIT_MINUTES, STALE_WARN_MINUTES,
    STATUS_CRITICAL, STATUS_OK, STATUS_WARNING, get_email_queue_health,
)
from classroom.models import EmailQueue


def _queue(minutes_old=0, status=EmailQueue.STATUS_PENDING, **kw):
    row = EmailQueue.objects.create(
        recipient_email=kw.pop('email', 'a@example.com'),
        subject='Invoice INV-4-2026-0001 — Maths Hub',
        from_email='noreply@example.com',
        html_content='<p>x</p>', text_content='x',
        notification_type=kw.pop('notification_type', 'invoice'),
        status=status, **kw,
    )
    if minutes_old:
        EmailQueue.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=minutes_old))
        row.refresh_from_db()
    return row


class EmailQueueHealthTest(TestCase):
    def test_empty_queue_is_ok(self):
        health = get_email_queue_health()
        self.assertEqual(health['status'], STATUS_OK)
        self.assertEqual(health['pending'], 0)
        self.assertEqual(health['reasons'], [])

    def test_fresh_pending_row_is_ok(self):
        """A row queued seconds ago is normal — the drain runs every 2 min."""
        _queue(minutes_old=1)
        self.assertEqual(get_email_queue_health()['status'], STATUS_OK)

    def test_row_older_than_warn_threshold_warns(self):
        _queue(minutes_old=STALE_WARN_MINUTES + 5)
        health = get_email_queue_health()
        self.assertEqual(health['status'], STATUS_WARNING)
        self.assertTrue(any('behind schedule' in r for r in health['reasons']))

    def test_row_older_than_crit_threshold_is_critical(self):
        """The real incident: rows aged for weeks because the cron was gone."""
        _queue(minutes_old=STALE_CRIT_MINUTES + 60)
        health = get_email_queue_health()
        self.assertEqual(health['status'], STATUS_CRITICAL)
        self.assertTrue(any('not running' in r for r in health['reasons']))

    def test_deep_backlog_warns_even_when_young(self):
        for i in range(DEPTH_WARN):
            _queue(email=f'r{i}@example.com')
        health = get_email_queue_health()
        self.assertEqual(health['status'], STATUS_WARNING)
        self.assertEqual(health['pending'], DEPTH_WARN)

    def test_failed_rows_are_reported(self):
        _queue(status=EmailQueue.STATUS_FAILED)
        health = get_email_queue_health()
        self.assertEqual(health['failed'], 1)
        self.assertEqual(health['status'], STATUS_WARNING)

    def test_sent_rows_do_not_count_as_pending(self):
        row = _queue(status=EmailQueue.STATUS_SENT)
        EmailQueue.objects.filter(pk=row.pk).update(sent_at=timezone.now())
        health = get_email_queue_health()
        self.assertEqual(health['pending'], 0)
        self.assertEqual(health['sent_today'], 1)
        self.assertEqual(health['status'], STATUS_OK)

    def test_pending_by_type_breakdown(self):
        _queue(notification_type='invoice')
        _queue(notification_type='welcome', email='b@example.com')
        health = get_email_queue_health()
        self.assertEqual(health['pending_by_type'], {'invoice': 1, 'welcome': 1})


class CheckEmailQueueHealthCommandTest(TestCase):
    def test_healthy_queue_exits_zero_and_posts_nothing(self):
        with patch('urllib.request.urlopen') as opened:
            call_command('check_email_queue_health', '--webhook', 'https://hook')
        opened.assert_not_called()

    def test_stalled_queue_exits_nonzero_and_alerts(self):
        _queue(minutes_old=STALE_CRIT_MINUTES + 60)
        with patch('urllib.request.urlopen') as opened:
            with self.assertRaises(SystemExit) as exit_ctx:
                call_command('check_email_queue_health', '--webhook', 'https://hook')
        self.assertEqual(exit_ctx.exception.code, 1)
        opened.assert_called_once()
        body = json.loads(opened.call_args[0][0].data.decode())
        self.assertIn('CRITICAL', body['content'])
        self.assertIn('process_email_queue', body['content'])

    def test_webhook_failure_does_not_crash_the_cron(self):
        """A dead webhook must not mask the alert with a traceback."""
        _queue(minutes_old=STALE_CRIT_MINUTES + 60)
        with patch('urllib.request.urlopen', side_effect=Exception('no route')):
            with self.assertRaises(SystemExit):
                call_command('check_email_queue_health', '--webhook', 'https://hook')

    def test_fail_on_critical_ignores_a_warning(self):
        _queue(minutes_old=STALE_WARN_MINUTES + 5)
        call_command('check_email_queue_health', '--fail-on', 'critical')  # no SystemExit


class DeepHealthEmailWarningTest(TestCase):
    def test_backlog_is_reported_but_does_not_fail_the_endpoint(self):
        """deploy.sh gates on a 200 here — a backlog must not block the deploy
        that would fix it."""
        _queue(minutes_old=STALE_CRIT_MINUTES + 60)

        response = Client().get('/api/health/?deep=1')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'ok')
        warning = body['warnings']['email_queue']
        self.assertEqual(warning['status'], 'critical')
        self.assertEqual(warning['pending'], 1)

    def test_healthy_queue_reports_ok(self):
        body = Client().get('/api/health/?deep=1').json()
        self.assertEqual(body['warnings']['email_queue']['status'], 'ok')

    def test_shallow_health_has_no_warnings_block(self):
        self.assertNotIn('warnings', Client().get('/api/health/').json())
