"""The one shared reading of a student's times-table results.

Three pages show these results and each used to work them out for itself. They
had already drifted — the wall read the highest-*points* run, the picker the
highest *score*, so one page could say 100% where the other said 92%. These
tests pin the single reading they all take now, and the rule it applies:

  latest leads, best follows.

A best score only ever goes up, so leading with it answers "what did this child
once do" and never "what can they do now". Leading with the latest and dropping
the best would cost a hard-won green tile to one distracted run, which is the
opposite of encouraging practice. So the tile shows both.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from maths import times_table_results as ttr
from maths.models import StudentFinalAnswer


class TimesTableResultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = get_user_model().objects.create_user(
            username='ttresults', email='ttr@example.com', password='pass1234',
        )

    def _attempt(self, table, operation, days_ago, *, score=12, points=90.0,
                 seconds=20, shuffled=False):
        return StudentFinalAnswer.objects.create(
            student=self.student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table, operation=operation, shuffled=shuffled,
            score=score, total_questions=12, points=points,
            time_taken_seconds=seconds,
            completed_at=timezone.now() - timedelta(days=days_ago),
        )

    def _entry(self, table=7, operation='multiplication'):
        return ttr.results_map(self.student)[(table, operation)]

    # ----- latest vs best -------------------------------------------------

    def test_latest_is_the_most_recent_attempt_however_bad(self):
        self._attempt(7, 'multiplication', days_ago=30, score=12, points=99.0)
        worst = self._attempt(7, 'multiplication', days_ago=1, score=2, points=3.0)
        entry = self._entry()
        self.assertEqual(entry['latest'].pk, worst.pk)
        self.assertEqual(entry['latest_pct'], 17)

    def test_best_survives_a_bad_latest_run(self):
        best = self._attempt(7, 'multiplication', days_ago=30, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=1, score=2, points=3.0)
        entry = self._entry()
        self.assertEqual(entry['best'].pk, best.pk)
        self.assertEqual(entry['best_pct'], 100)
        self.assertFalse(entry['latest_is_best'])

    def test_a_single_attempt_is_both_latest_and_best(self):
        only = self._attempt(7, 'multiplication', days_ago=1, score=9)
        entry = self._entry()
        self.assertEqual(entry['latest'].pk, only.pk)
        self.assertEqual(entry['best'].pk, only.pk)
        self.assertTrue(entry['latest_is_best'])

    def test_two_runs_of_equal_score_do_not_claim_the_slow_one_matched(self):
        # Compared on the attempt, not the percentage: both score 100%, but the
        # fast one is the record and today's slow one should not claim it.
        self._attempt(7, 'multiplication', days_ago=30, score=12, points=99.0,
                      seconds=10)
        self._attempt(7, 'multiplication', days_ago=1, score=12, points=40.0,
                      seconds=55)
        entry = self._entry()
        self.assertEqual(entry['latest_pct'], 100)
        self.assertEqual(entry['best_pct'], 100)
        self.assertFalse(entry['latest_is_best'])

    def test_latest_spans_both_modes(self):
        # Shuffled and in-order are separate scores but either is "the last
        # time this child did this table".
        self._attempt(8, 'multiplication', days_ago=30, shuffled=True, score=12)
        recent = self._attempt(8, 'multiplication', days_ago=1, shuffled=False,
                               score=6)
        self.assertEqual(self._entry(8)['latest'].pk, recent.pk)

    def test_best_keeps_the_walls_shuffle_preference(self):
        # The long-standing rule: a shuffled run under 2x the ordered time is
        # the more impressive result and is the one shown as best.
        shuffled = self._attempt(8, 'multiplication', days_ago=5, shuffled=True,
                                 points=80.0, seconds=25)
        self._attempt(8, 'multiplication', days_ago=4, shuffled=False,
                      points=95.0, seconds=20)
        self.assertEqual(self._entry(8)['best'].pk, shuffled.pk)

    def test_a_slow_shuffled_run_does_not_beat_a_fast_ordered_one(self):
        self._attempt(8, 'multiplication', days_ago=5, shuffled=True,
                      points=80.0, seconds=90)
        ordered = self._attempt(8, 'multiplication', days_ago=4, shuffled=False,
                                points=95.0, seconds=20)
        self.assertEqual(self._entry(8)['best'].pk, ordered.pk)

    # ----- shape ----------------------------------------------------------

    def test_operations_are_read_separately(self):
        self._attempt(6, 'multiplication', days_ago=1, score=12)
        self._attempt(6, 'division', days_ago=1, score=6)
        results = ttr.results_map(self.student)
        self.assertEqual(results[(6, 'multiplication')]['latest_pct'], 100)
        self.assertEqual(results[(6, 'division')]['latest_pct'], 50)

    def test_legacy_rows_with_no_operation_read_as_multiplication(self):
        self._attempt(9, '', days_ago=3, score=12)
        results = ttr.results_map(self.student)
        self.assertIn((9, 'multiplication'), results)
        self.assertEqual(results[(9, 'multiplication')]['latest_pct'], 100)

    def test_a_table_never_attempted_is_simply_absent(self):
        self._attempt(7, 'multiplication', days_ago=1)
        self.assertNotIn((11, 'multiplication'), ttr.results_map(self.student))

    def test_an_attempt_with_no_questions_has_no_percentage(self):
        StudentFinalAnswer.objects.create(
            student=self.student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=5, operation='multiplication',
            score=0, total_questions=0, points=0.0, time_taken_seconds=0,
        )
        entry = self._entry(5)
        self.assertIsNone(entry['latest_pct'])
        self.assertIsNone(entry['best_pct'])

    def test_freshness_rides_along_with_the_latest_attempt(self):
        self._attempt(7, 'multiplication', days_ago=200)
        self.assertEqual(self._entry()['freshness']['state'], 'stale')

    def test_tables_needing_refresh_lists_each_table_once(self):
        self._attempt(3, 'multiplication', days_ago=200)
        self._attempt(3, 'division', days_ago=200)
        self._attempt(5, 'multiplication', days_ago=50)
        self._attempt(2, 'multiplication', days_ago=1)
        self.assertEqual(
            ttr.tables_needing_refresh(ttr.results_map(self.student)), [3, 5])

    # ----- the wall builder both dashboards share -------------------------

    def test_wall_tiles_colour_from_the_latest_attempt(self):
        self._attempt(7, 'multiplication', days_ago=30, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=1, score=4, points=5.0)
        tiles, _ = ttr.wall_tiles(self.student, lambda a: f'pk-{a.pk if a else None}')
        row = next(r for r in tiles[6]['rows'] if r['symbol'] == '×')
        self.assertEqual(row['colour'], f"pk-{row['result']['latest'].pk}")

    def test_wall_tiles_cover_every_table_even_untouched_ones(self):
        self._attempt(7, 'multiplication', days_ago=1)
        tiles, refresh_due = ttr.wall_tiles(self.student, lambda a: '')
        self.assertEqual([t['table'] for t in tiles], list(range(1, 16)))
        self.assertEqual(refresh_due, [])
        untouched = next(t for t in tiles if t['table'] == 12)
        self.assertTrue(all(row['result'] is None for row in untouched['rows']))
        self.assertFalse(untouched['needs_refresh'])

    def test_wall_tiles_carry_both_operations_in_order(self):
        tiles, _ = ttr.wall_tiles(self.student, lambda a: '')
        self.assertEqual([r['symbol'] for r in tiles[0]['rows']], ['×', '÷'])

    def test_nothing_is_deleted_by_reading_results(self):
        # The guard on the original "expire after 3 months" idea:
        # rewards.rebuild_points_ledger awards from the best attempt ever made.
        self._attempt(4, 'multiplication', days_ago=365, points=99.0)
        ttr.results_map(self.student)
        ttr.wall_tiles(self.student, lambda a: '')
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student).count(), 1)
        self.assertEqual(
            StudentFinalAnswer.objects.get(student=self.student).points, 99.0)
