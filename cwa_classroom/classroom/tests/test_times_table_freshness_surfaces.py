"""The times-table wall leads with the latest attempt and keeps the best.

Both views that render ``student/dashboard.html`` are covered — the classroom
dashboard and the progress dashboard — because they render the SAME template
and used to assemble their tiles separately, which is how one of them ended up
with the freshness nudges and the other without.

The rule under test: the headline number, the colour and the date all come from
the student's LATEST attempt, and their best is still reported beside it. A best
score only ever goes up, so leading with it answered "what did this child once
do"; leading with the latest and dropping the best would cost a hard-won green
tile to one distracted run.
"""
import datetime

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.progress_summary import maths_summary
from maths.models import StudentFinalAnswer

from .test_e2e_attendance_progress import _BaseAttendanceProgressTest


class TimesTableWallTest(_BaseAttendanceProgressTest):

    def _attempt(self, table, operation, days_ago, score=12, points=90.0,
                 seconds=20, shuffled=False):
        return StudentFinalAnswer.objects.create(
            student=self.student_user, level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table, operation=operation, attempt_number=1,
            score=score, total_questions=12, points=points, shuffled=shuffled,
            time_taken_seconds=seconds,
            completed_at=timezone.now() - datetime.timedelta(days=days_ago),
        )

    def _wall(self, url_name='student_dashboard'):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse(url_name))
        self.assertEqual(response.status_code, 200)
        by_table = {t['table']: t for t in response.context['tt_results']}
        return response, by_table

    @staticmethod
    def _row(tile, symbol='×'):
        return next(r for r in tile['rows'] if r['symbol'] == symbol)

    # ----- Latest leads --------------------------------------------------

    def test_the_tile_leads_with_the_latest_attempt_not_the_best(self):
        # The change in one test: a brilliant old run and a weak recent one.
        # The headline is the weak recent one, because that is where the
        # student actually is today.
        self._attempt(7, 'multiplication', days_ago=60, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=1, score=6, points=20.0)

        _, wall = self._wall()
        row = self._row(wall[7])
        self.assertEqual(row['result']['latest_pct'], 50)
        self.assertEqual(row['result']['best_pct'], 100)
        self.assertFalse(row['result']['latest_is_best'])

    def test_the_best_is_kept_so_an_off_day_does_not_erase_it(self):
        self._attempt(7, 'multiplication', days_ago=30, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=1, score=3, points=5.0)
        _, wall = self._wall()
        self.assertEqual(self._row(wall[7])['result']['best_pct'], 100)

    def test_a_personal_best_today_is_marked_as_such(self):
        self._attempt(7, 'multiplication', days_ago=30, score=6, points=20.0)
        self._attempt(7, 'multiplication', days_ago=1, score=12, points=99.0)
        _, wall = self._wall()
        row = self._row(wall[7])
        self.assertTrue(row['result']['latest_is_best'])
        self.assertEqual(row['result']['latest_pct'], 100)

    def test_the_colour_follows_the_latest_attempt(self):
        # Colour and date now describe the same run. A perfect old score with a
        # failed recent one must not still be painted green.
        self._attempt(7, 'multiplication', days_ago=30, score=12, points=99.0,
                      seconds=10, shuffled=True)
        _, green_wall = self._wall()
        green = self._row(green_wall[7])['colour']
        self.assertIn('green', green)

        self._attempt(7, 'multiplication', days_ago=0, score=4, points=5.0)
        _, now_wall = self._wall()
        self.assertIn('red', self._row(now_wall[7])['colour'])

    def test_merely_ageing_does_not_change_the_colour(self):
        # Staleness qualifies a result; it never demotes it. Only a NEW, worse
        # attempt changes the colour.
        self._attempt(7, 'multiplication', days_ago=1, score=12, points=99.0,
                      seconds=10, shuffled=True)
        _, fresh_wall = self._wall()
        fresh_colour = self._row(fresh_wall[7])['colour']

        StudentFinalAnswer.objects.filter(student=self.student_user).update(
            completed_at=timezone.now() - datetime.timedelta(days=200))
        _, stale_wall = self._wall()
        self.assertEqual(self._row(stale_wall[7])['colour'], fresh_colour)
        self.assertTrue(stale_wall[7]['needs_refresh'])

    # ----- Freshness still works ----------------------------------------

    def test_a_stale_table_is_flagged_on_the_wall(self):
        self._attempt(7, 'multiplication', days_ago=150)
        response, wall = self._wall()
        self.assertTrue(wall[7]['needs_refresh'])
        self.assertEqual(self._row(wall[7])['result']['freshness']['state'], 'stale')
        self.assertEqual(response.context['tt_refresh_due'], [7])

    def test_a_fresh_table_is_left_alone(self):
        self._attempt(7, 'multiplication', days_ago=2)
        response, wall = self._wall()
        self.assertFalse(wall[7]['needs_refresh'])
        self.assertEqual(response.context['tt_refresh_due'], [])

    def test_an_unattempted_table_carries_nothing_at_all(self):
        self._attempt(7, 'multiplication', days_ago=200)
        _, wall = self._wall()
        self.assertIsNone(self._row(wall[8])['result'])
        self.assertFalse(wall[8]['needs_refresh'])

    def test_legacy_rows_with_no_operation_fill_the_multiplication_row(self):
        self._attempt(9, '', days_ago=10, score=12)
        _, wall = self._wall()
        self.assertEqual(self._row(wall[9])['result']['latest_pct'], 100)

    def test_nothing_is_deleted_by_rendering_the_wall(self):
        # Expiring the ROWS would silently lower a student's points the next
        # time rewards.rebuild_points_ledger runs, which reads the best attempt
        # a student ever made.
        self._attempt(7, 'multiplication', days_ago=500, points=99.0)
        self._wall()
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student_user).count(), 1)
        self.assertEqual(
            StudentFinalAnswer.objects.get(student=self.student_user).points, 99.0)

    # ----- The second view that renders the same template ----------------

    def test_the_progress_dashboard_builds_the_same_wall(self):
        """progress.views renders student/dashboard.html too, and must agree.

        It is not reached through a URL today: progress/urls.py registers
        'student-dashboard/' under the same name as classroom/urls.py, which is
        included first in the root urlconf and wins, so this view is shadowed
        dead code. That is exactly why it drifted — it built its own tiles and
        never grew the freshness nudges the live wall has. It is driven
        directly here so the two cannot diverge again while the duplicate URL
        stands; if the view is ever deleted, delete this test with it.
        """
        from unittest.mock import patch

        from django.http import HttpResponse
        from django.test import RequestFactory

        from progress.views import StudentDashboardView

        self._attempt(7, 'multiplication', days_ago=150, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=140, score=6, points=20.0)

        _, classroom_wall = self._wall('student_dashboard')

        # The view is driven directly and its context captured at the render
        # call: no URL reaches it, and rendering the full dashboard template
        # would only re-test the template the live wall already covers.
        request = RequestFactory().get('/student-dashboard/')
        request.user = self.student_user
        captured = {}

        def _capture(req, template, context, *args, **kwargs):
            captured.update(context)
            return HttpResponse(b'')

        with patch('progress.views.render', _capture):
            StudentDashboardView.as_view()(request)

        progress_wall = {t['table']: t for t in captured['tt_results']}

        self.assertEqual(
            self._row(progress_wall[7])['result']['latest_pct'],
            self._row(classroom_wall[7])['result']['latest_pct'],
        )
        self.assertEqual(
            self._row(progress_wall[7])['colour'],
            self._row(classroom_wall[7])['colour'],
        )
        self.assertTrue(progress_wall[7]['needs_refresh'])
        self.assertEqual(captured['tt_refresh_due'], [7])


class TimesTableSummaryTest(_BaseAttendanceProgressTest):
    """The teacher/parent progress summary tells the same story."""

    def _attempt(self, table, operation, days_ago, score=12, points=90.0):
        return StudentFinalAnswer.objects.create(
            student=self.student_user, level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table, operation=operation, attempt_number=1,
            score=score, total_questions=12, points=points,
            time_taken_seconds=20,
            completed_at=timezone.now() - datetime.timedelta(days=days_ago),
        )

    def _row(self):
        return maths_summary(self.student_user, times_tables=True)['times_tables'][0]

    def test_the_summary_reports_the_latest_score_with_the_best_beside_it(self):
        self._attempt(7, 'multiplication', days_ago=60, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=2, score=9, points=40.0)
        row = self._row()
        self.assertEqual(row['table'], 7)
        self.assertEqual(row['multiplication_pct'], 75)
        self.assertEqual(row['multiplication_best_pct'], 100)

    def test_an_operation_never_tried_is_none_on_both_counts(self):
        self._attempt(7, 'multiplication', days_ago=2, score=12)
        row = self._row()
        self.assertIsNone(row['division_pct'])
        self.assertIsNone(row['division_best_pct'])

    def test_the_summary_reports_when_a_table_was_last_practised(self):
        self._attempt(7, 'multiplication', days_ago=150, score=12)
        row = self._row()
        self.assertEqual(row['freshness'], 'stale')
        self.assertTrue(row['needs_refresh'])
        self.assertTrue(row['last_practised_ago'])

    def test_the_summary_takes_the_later_of_the_two_operations(self):
        # "When did this child last do their 7s" — division last week counts.
        self._attempt(7, 'multiplication', days_ago=200)
        self._attempt(7, 'division', days_ago=4)
        row = self._row()
        self.assertEqual(row['freshness'], 'fresh')
        self.assertFalse(row['needs_refresh'])

    @override_settings(TIMES_TABLE_FRESH_DAYS=7, TIMES_TABLE_STALE_DAYS=14)
    def test_the_summary_respects_the_configured_window(self):
        self._attempt(7, 'multiplication', days_ago=10)
        row = self._row()
        self.assertEqual(row['freshness'], 'due')
        self.assertTrue(row['needs_refresh'])
