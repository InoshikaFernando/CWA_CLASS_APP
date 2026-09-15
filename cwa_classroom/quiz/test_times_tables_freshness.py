"""The times-tables picker: latest score, best beside it, and a staleness nudge.

Before this, the picker was twelve identical doors: no score, no date, nothing
to say which tables were solid and which had not been opened since last term.

It leads with the student's LATEST score rather than their best, because a best
score never goes down and so cannot say how a child is doing now — and keeps
the best beside it, because leading with the latest alone would cost a hard-won
100% to one off day.

Nothing is expired here — the scores stand and stay in the database (see
maths/tests/test_times_table_freshness.py for why deleting them would take
points off students).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.models import Level
from maths.models import StudentFinalAnswer

User = get_user_model()


class TimesTablesPickerFreshnessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='ttpicker', password='pass1234', email='ttp@test.com',
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')

    def setUp(self):
        self.client = Client()
        self.client.login(username='ttpicker', password='pass1234')

    def _attempt(self, table, operation, days_ago, score=12, points=90.0):
        return StudentFinalAnswer.objects.create(
            student=self.student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table, operation=operation,
            score=score, total_questions=12, points=points,
            time_taken_seconds=20,
            completed_at=timezone.now() - timedelta(days=days_ago),
        )

    def _tiles(self):
        response = self.client.get(reverse('times_tables_home'))
        self.assertEqual(response.status_code, 200)
        return response, {t['table']: t for t in response.context['tiles']}

    def test_a_recently_practised_table_is_not_nudged(self):
        self._attempt(7, 'multiplication', days_ago=3)
        response, tiles = self._tiles()
        self.assertFalse(tiles[7]['needs_refresh'])
        self.assertEqual(response.context['refresh_due'], [])
        self.assertNotContains(response, 'Needs a refresh')

    def test_a_table_untouched_for_three_months_asks_for_a_refresh(self):
        self._attempt(7, 'multiplication', days_ago=120)
        response, tiles = self._tiles()
        self.assertTrue(tiles[7]['needs_refresh'])
        self.assertEqual(response.context['refresh_due'], [7])
        self.assertContains(response, 'Needs a refresh')
        self.assertContains(response, 'Time to revisit')

    def test_the_old_score_is_still_shown_not_hidden(self):
        # The nudge qualifies the result; it never replaces or erases it.
        self._attempt(7, 'multiplication', days_ago=120, score=12)
        response, tiles = self._tiles()
        self.assertEqual(tiles[7]['mul']['latest_pct'], 100)
        self.assertContains(response, '100%')
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student).count(), 1)

    def test_the_tile_leads_with_the_latest_score_and_keeps_the_best(self):
        self._attempt(7, 'multiplication', days_ago=40, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=1, score=6, points=20.0)
        response, tiles = self._tiles()
        self.assertEqual(tiles[7]['mul']['latest_pct'], 50)
        self.assertEqual(tiles[7]['mul']['best_pct'], 100)
        # Both numbers reach the page: today's score, and the record it has
        # not taken away.
        self.assertContains(response, '50%')
        self.assertContains(response, 'best')
        self.assertContains(response, '100%')

    def test_the_best_is_not_repeated_when_today_is_the_best(self):
        # Echoing "best 100%" under a 100% tile is noise.
        self._attempt(7, 'multiplication', days_ago=1, score=12, points=99.0)
        response, tiles = self._tiles()
        self.assertTrue(tiles[7]['mul']['latest_is_best'])
        self.assertNotContains(response, 'best')

    def test_a_table_never_attempted_is_not_nudged(self):
        self._attempt(7, 'multiplication', days_ago=120)
        _, tiles = self._tiles()
        self.assertFalse(tiles[8]['needs_refresh'])
        self.assertIsNone(tiles[8]['mul'])
        self.assertIsNone(tiles[8]['div'])

    def test_locked_tables_are_never_nudged(self):
        # Year 4 cannot practise the 9 times table, so asking them to refresh
        # it would be a chore with no way to do it.
        stale = self._attempt(9, 'multiplication', days_ago=200)
        self.assertTrue(stale.pk)
        response, tiles = self._tiles()
        self.assertFalse(tiles[9]['unlocked'])
        self.assertEqual(response.context['refresh_due'], [])

    def test_the_picker_shows_the_latest_score_per_operation(self):
        self._attempt(7, 'multiplication', days_ago=10, score=6)
        self._attempt(7, 'multiplication', days_ago=8, score=12)
        self._attempt(7, 'division', days_ago=8, score=9)
        _, tiles = self._tiles()
        self.assertEqual(tiles[7]['mul']['latest_pct'], 100)
        self.assertEqual(tiles[7]['div']['latest_pct'], 75)

    def test_the_picker_and_the_wall_agree_about_the_same_table(self):
        # They read the same helper now. They used to disagree: the picker took
        # the highest SCORE and the wall the highest-POINTS run, so one page
        # could say 100% where the other said 50%.
        from maths import times_table_results

        self._attempt(7, 'multiplication', days_ago=10, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=2, score=6, points=20.0)
        _, tiles = self._tiles()
        shared = times_table_results.results_map(self.student)
        self.assertEqual(
            tiles[7]['mul']['latest_pct'],
            shared[(7, 'multiplication')]['latest_pct'],
        )

    def test_a_stale_multiplication_nudges_even_when_division_is_fresh(self):
        self._attempt(7, 'multiplication', days_ago=200)
        self._attempt(7, 'division', days_ago=1)
        _, tiles = self._tiles()
        self.assertTrue(tiles[7]['needs_refresh'])
        self.assertEqual(tiles[7]['mul']['freshness']['state'], 'stale')
        self.assertEqual(tiles[7]['div']['freshness']['state'], 'fresh')

    @override_settings(TIMES_TABLE_FRESH_DAYS=7, TIMES_TABLE_STALE_DAYS=14)
    def test_the_window_is_configurable(self):
        self._attempt(7, 'multiplication', days_ago=10)
        response, tiles = self._tiles()
        self.assertTrue(tiles[7]['needs_refresh'])
        self.assertEqual(response.context['refresh_due'], [7])

    def test_legacy_attempts_with_no_operation_still_get_a_date(self):
        self._attempt(7, '', days_ago=200)
        _, tiles = self._tiles()
        self.assertEqual(tiles[7]['mul']['latest_pct'], 100)
        self.assertTrue(tiles[7]['needs_refresh'])

    def test_a_student_with_no_history_sees_a_clean_page(self):
        response, tiles = self._tiles()
        self.assertEqual(response.context['refresh_due'], [])
        self.assertContains(response, 'Not tried yet')
        self.assertNotContains(response, 'Needs a refresh')

    def test_the_operation_picker_page_carries_the_same_nudges(self):
        # TimesTablesSelectView renders the same template from a different URL;
        # it would be the one place the warning silently went missing.
        self._attempt(7, 'multiplication', days_ago=120)
        response = self.client.get(
            reverse('multiplication_select', kwargs={'level_number': 4}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['refresh_due'], [7])
        self.assertContains(response, 'Needs a refresh')
