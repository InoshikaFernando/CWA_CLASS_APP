"""Freshness reaches the two places a times-table result is read: the student's
dashboard wall and the teacher/parent progress summary.

The wall colours a tile from the student's BEST attempt, which never expires —
so a table mastered last term showed dark green today with no date against it.
These tests pin the fix: the colour is untouched and the attempt rows survive,
and the staleness label beside them comes from the LATEST attempt.
"""
import datetime

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.progress_summary import maths_summary
from maths.models import StudentFinalAnswer

from .test_e2e_attendance_progress import _BaseAttendanceProgressTest


class TimesTableFreshnessSurfaceTest(_BaseAttendanceProgressTest):

    def _attempt(self, table, operation, days_ago, score=12, points=90.0):
        return StudentFinalAnswer.objects.create(
            student=self.student_user, level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table, operation=operation, attempt_number=1,
            score=score, total_questions=12, points=points,
            time_taken_seconds=20,
            completed_at=timezone.now() - datetime.timedelta(days=days_ago),
        )

    # ----- The student's dashboard wall -----------------------------------

    def _wall(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student_dashboard'))
        self.assertEqual(response.status_code, 200)
        return response, {r['table']: r for r in response.context['tt_results']}

    def test_a_stale_table_is_flagged_on_the_wall(self):
        self._attempt(7, 'multiplication', days_ago=150)
        response, wall = self._wall()
        self.assertTrue(wall[7]['needs_refresh'])
        self.assertEqual(wall[7]['mul_fresh']['state'], 'stale')
        self.assertEqual(response.context['tt_refresh_due'], [7])

    def test_a_fresh_table_is_left_alone(self):
        self._attempt(7, 'multiplication', days_ago=2)
        response, wall = self._wall()
        self.assertFalse(wall[7]['needs_refresh'])
        self.assertEqual(response.context['tt_refresh_due'], [])

    def test_the_earned_colour_does_not_change_when_a_result_goes_stale(self):
        # The whole design: staleness qualifies the result, it never demotes
        # it. A child who earned dark green keeps dark green.
        self._attempt(7, 'multiplication', days_ago=1)
        _, fresh_wall = self._wall()
        fresh_colour = fresh_wall[7]['mul_colour']

        StudentFinalAnswer.objects.filter(student=self.student_user).update(
            completed_at=timezone.now() - datetime.timedelta(days=200))
        _, stale_wall = self._wall()
        self.assertEqual(stale_wall[7]['mul_colour'], fresh_colour)
        self.assertTrue(stale_wall[7]['needs_refresh'])

    def test_nothing_is_deleted_by_looking_at_the_wall(self):
        # Expiring the ROWS would silently lower a student's points the next
        # time rewards.rebuild_points_ledger runs, which reads the best attempt
        # a student ever made.
        self._attempt(7, 'multiplication', days_ago=500, points=99.0)
        self._wall()
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student_user).count(), 1)
        self.assertEqual(
            StudentFinalAnswer.objects.get(student=self.student_user).points, 99.0)

    def test_an_unattempted_table_carries_no_freshness_at_all(self):
        self._attempt(7, 'multiplication', days_ago=200)
        _, wall = self._wall()
        self.assertIsNone(wall[8]['mul_fresh'])
        self.assertFalse(wall[8]['needs_refresh'])

    # ----- The teacher / parent progress summary --------------------------

    def test_the_summary_reports_when_a_table_was_last_practised(self):
        self._attempt(7, 'multiplication', days_ago=150, score=12)
        row = maths_summary(self.student_user, times_tables=True)['times_tables'][0]
        self.assertEqual(row['table'], 7)
        # The best score still stands...
        self.assertEqual(row['multiplication_pct'], 100)
        # ...and is now qualified by when it was last shown to be true.
        self.assertEqual(row['freshness'], 'stale')
        self.assertTrue(row['needs_refresh'])
        self.assertTrue(row['last_practised_ago'])

    def test_the_summary_takes_the_later_of_the_two_operations(self):
        # "When did this child last do their 7s" — division last week counts.
        self._attempt(7, 'multiplication', days_ago=200)
        self._attempt(7, 'division', days_ago=4)
        row = maths_summary(self.student_user, times_tables=True)['times_tables'][0]
        self.assertEqual(row['freshness'], 'fresh')
        self.assertFalse(row['needs_refresh'])

    @override_settings(TIMES_TABLE_FRESH_DAYS=7, TIMES_TABLE_STALE_DAYS=14)
    def test_the_summary_respects_the_configured_window(self):
        self._attempt(7, 'multiplication', days_ago=10)
        row = maths_summary(self.student_user, times_tables=True)['times_tables'][0]
        self.assertEqual(row['freshness'], 'due')
        self.assertTrue(row['needs_refresh'])
