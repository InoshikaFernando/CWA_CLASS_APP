"""
Tests for the scheduled-publish health signal (homework/publish_health.py).

The failure this exists for: ``publish_scheduled_homework`` is the only thing
that sets ``published_at``, its cron drop-in is written by the one-time
provisioning script rather than by a deploy, and when it is missing the
question-automation schedule keeps building sets that are never sent — with
nothing erroring anywhere. These tests pin the signal that makes that state
loud, so it cannot regress back into silence.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from . import schedule_services as svc
from .models import Homework, HomeworkQuestion
from .publish_health import (
    STALE_CRIT_MINUTES, STALE_WARN_MINUTES, get_scheduled_publish_health,
)
from .tests_schedule import ScheduleTestBase


class ScheduledSetMixin(ScheduleTestBase):
    """Fixtures only — the assertions live in the two classes below."""

    def _scheduled(self, minutes_ago=None, minutes_ahead=None, title='Set'):
        """A homework with a publish_at and no published_at — the state the
        cron is responsible for clearing."""
        if minutes_ago is not None:
            publish_at = timezone.now() - timedelta(minutes=minutes_ago)
        else:
            publish_at = timezone.now() + timedelta(minutes=minutes_ahead)
        hw = Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher,
            title=title,
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
            publish_at=publish_at,
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(
                homework=hw, question=q, subject_slug='mathematics',
                content_id=q.pk, order=i,
            )
        return hw


class PublishHealthTest(ScheduledSetMixin):
    def test_nothing_scheduled_is_healthy(self):
        health = get_scheduled_publish_health()
        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['reasons'], [])
        self.assertEqual(health['overdue'], 0)
        self.assertIsNone(health['oldest_overdue_min'])

    def test_a_set_inside_its_preview_window_is_healthy(self):
        """The gap between generation and release is the feature working, not a
        backlog: an unpublished set whose release time has not arrived is
        exactly what the teacher is supposed to be previewing."""
        self._scheduled(minutes_ahead=60 * 24)

        health = get_scheduled_publish_health()

        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['overdue'], 0)
        self.assertEqual(health['upcoming'], 1)

    def test_a_set_a_tick_or_two_late_is_still_healthy(self):
        """The cron runs every five minutes, so a set a few minutes past its
        release time is a tick away from fine — alerting there would cry wolf
        several times a day."""
        self._scheduled(minutes_ago=STALE_WARN_MINUTES - 5)

        self.assertEqual(get_scheduled_publish_health()['status'], 'ok')

    def test_a_set_past_several_ticks_warns(self):
        self._scheduled(minutes_ago=STALE_WARN_MINUTES + 5)

        health = get_scheduled_publish_health()

        self.assertEqual(health['status'], 'warning')
        self.assertEqual(health['overdue'], 1)
        self.assertTrue(any('behind schedule' in r for r in health['reasons']))

    def test_a_set_hours_past_its_release_is_critical(self):
        self._scheduled(minutes_ago=STALE_CRIT_MINUTES + 60, title='Monday set')

        health = get_scheduled_publish_health()

        self.assertEqual(health['status'], 'critical')
        self.assertTrue(any('is not running' in r for r in health['reasons']))
        self.assertEqual(health['rows'][0]['title'], 'Monday set')
        self.assertEqual(health['rows'][0]['classroom'], self.classroom.name)

    def test_running_the_publish_command_clears_the_alarm(self):
        """The signal must track the cron, not merely the existence of rows —
        otherwise the fix would not show up as a fix."""
        self._scheduled(minutes_ago=STALE_CRIT_MINUTES + 60)
        self.assertEqual(get_scheduled_publish_health()['status'], 'critical')

        call_command('publish_scheduled_homework', stdout=StringIO())

        health = get_scheduled_publish_health()
        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['overdue'], 0)
        self.assertIsNotNone(health['last_published_at'])

    def test_manual_publish_now_does_not_look_like_a_live_cron(self):
        """A teacher publishing by hand is what a dead cron looks like from the
        outside — it is the workaround, not evidence the job ran. Counting it
        as a release would have hidden exactly the incident this exists for."""
        Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher,
            title='Published by hand',
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
        )  # no publish_at: save() stamps published_at immediately

        health = get_scheduled_publish_health()

        self.assertIsNone(health['last_published_at'])

    def test_soft_deleted_sets_are_not_reported(self):
        """The publish command skips soft-deleted rows, so the signal must too
        or a deleted set would alarm forever."""
        hw = self._scheduled(minutes_ago=STALE_CRIT_MINUTES + 60)
        hw.soft_delete(self.teacher)

        health = get_scheduled_publish_health()

        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['overdue'], 0)

    def test_schedule_built_sets_are_named_as_such(self):
        """A set the automation built is the worse case: no human ever chose to
        send it, so nobody is waiting to notice it did not arrive."""
        schedule = self.make_schedule()
        week = self.plan_week(schedule, 1)
        result = svc.generate_week(week, force=True)
        homework = result.homework
        self.assertIsNotNone(homework)
        Homework.objects.filter(pk=homework.pk).update(
            publish_at=timezone.now() - timedelta(minutes=STALE_CRIT_MINUTES + 60),
        )

        health = get_scheduled_publish_health()

        self.assertEqual(health['status'], 'critical')
        self.assertEqual(health['from_schedule'], 1)
        self.assertTrue(health['rows'][0]['from_schedule'])
        self.assertTrue(any('question schedule' in r for r in health['reasons']))


class DeepHealthScheduledPublishWarningTest(ScheduledSetMixin):
    """The dashboard is behind a superuser login; this endpoint is what an
    uptime monitor can watch."""

    def test_a_stalled_publish_warns_without_failing_the_endpoint(self):
        """scripts/deploy.sh gates on a 200 here — a stalled publish must not
        block the deploy that ships the fix for it."""
        self._scheduled(minutes_ago=STALE_CRIT_MINUTES + 60)

        response = Client().get('/api/health/?deep=1')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        warning = response.json()['warnings']['scheduled_publish']
        self.assertEqual(warning['status'], 'critical')
        self.assertEqual(warning['overdue'], 1)
        self.assertTrue(warning['reasons'])

    def test_healthy_publishing_reports_ok(self):
        warning = Client().get('/api/health/?deep=1').json()[
            'warnings']['scheduled_publish']

        self.assertEqual(warning['status'], 'ok')
        self.assertEqual(warning['overdue'], 0)
        self.assertIn('oldest_overdue_minutes', warning)
