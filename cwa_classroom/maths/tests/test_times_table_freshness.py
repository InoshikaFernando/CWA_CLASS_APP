"""Times-table results are never expired — they are labelled as getting old.

The proposal these tests pin down was originally "delete times-table answers
after three months so all results are new". The reason it is a display rule
instead: ``rewards.rebuild_points_ledger`` awards times-table points from the
best attempt a student has ever made, so deleting attempts silently lowers
totals students already earned. Freshness is therefore derived, never stored
and never destructive — the assertions below say so in both directions.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from maths import times_table_freshness as ttf
from maths.models import StudentFinalAnswer


def _days_ago(days):
    return timezone.now() - timedelta(days=days)


class FreshnessStateTests(TestCase):
    """The pure state machine — no database, no student."""

    def test_never_practised_is_its_own_state(self):
        # "Never done" must not read as "gone stale": the picker already shows
        # these grey, and nudging about a table nobody has opened is noise.
        self.assertEqual(ttf.state_for(None), ttf.NEVER)
        self.assertIsNone(ttf.days_since(None))

    def test_recent_attempt_is_fresh(self):
        self.assertEqual(ttf.state_for(_days_ago(3)), ttf.FRESH)

    def test_six_weeks_is_the_first_nudge(self):
        self.assertEqual(ttf.state_for(_days_ago(41)), ttf.FRESH)
        self.assertEqual(ttf.state_for(_days_ago(42)), ttf.DUE)

    def test_three_months_is_stale(self):
        self.assertEqual(ttf.state_for(_days_ago(89)), ttf.DUE)
        self.assertEqual(ttf.state_for(_days_ago(90)), ttf.STALE)
        self.assertEqual(ttf.state_for(_days_ago(400)), ttf.STALE)

    def test_a_future_timestamp_reads_as_today(self):
        # Imported rows have carried skewed clocks before. A negative age must
        # not come out as "fresher than fresh" or a negative day count.
        future = timezone.now() + timedelta(days=5)
        self.assertEqual(ttf.days_since(future), 0)
        self.assertEqual(ttf.state_for(future), ttf.FRESH)

    @override_settings(TIMES_TABLE_FRESH_DAYS=7, TIMES_TABLE_STALE_DAYS=14)
    def test_thresholds_are_tunable(self):
        self.assertEqual(ttf.state_for(_days_ago(8)), ttf.DUE)
        self.assertEqual(ttf.state_for(_days_ago(20)), ttf.STALE)

    @override_settings(TIMES_TABLE_FRESH_DAYS=60, TIMES_TABLE_STALE_DAYS=30)
    def test_stale_never_comes_before_due(self):
        # Misconfigured the wrong way round, the gentler state would be
        # unreachable. It is clamped rather than obeyed.
        self.assertEqual(ttf.stale_after_days(), 60)
        self.assertEqual(ttf.state_for(_days_ago(45)), ttf.FRESH)
        self.assertEqual(ttf.state_for(_days_ago(65)), ttf.STALE)

    def test_describe_carries_what_a_template_needs(self):
        info = ttf.describe(_days_ago(100))
        self.assertEqual(info['state'], ttf.STALE)
        self.assertEqual(info['days'], 100)
        self.assertTrue(info['needs_refresh'])
        self.assertEqual(info['label'], 'Needs a refresh')
        self.assertTrue(info['wash'])
        # One unit only — "3 months, 1 week" is precision nobody asked for.
        self.assertNotIn(',', info['ago'])

    def test_a_fresh_result_is_decorated_with_nothing(self):
        info = ttf.describe(_days_ago(1))
        self.assertFalse(info['needs_refresh'])
        self.assertEqual(info['label'], '')
        self.assertEqual(info['wash'], '')


class FreshnessQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = get_user_model().objects.create_user(
            username='ttfresh', email='ttfresh@example.com', password='pass1234',
        )

    def _attempt(self, table, operation, days_ago, *, score=12, points=90.0,
                 shuffled=False):
        return StudentFinalAnswer.objects.create(
            student=self.student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table, operation=operation, shuffled=shuffled,
            score=score, total_questions=12, points=points,
            time_taken_seconds=20, completed_at=_days_ago(days_ago),
        )

    def test_freshness_follows_the_latest_attempt_not_the_best(self):
        # The whole point: a brilliant old score and a scrappy recent one means
        # the table IS being practised. Reading the best attempt's date would
        # call it stale and nag a child who did it last week.
        self._attempt(7, 'multiplication', days_ago=200, score=12, points=99.0)
        self._attempt(7, 'multiplication', days_ago=2, score=5, points=10.0)

        info = ttf.describe_map(self.student)[(7, 'multiplication')]
        self.assertEqual(info['state'], ttf.FRESH)
        self.assertEqual(info['days'], 2)

    def test_shuffled_and_in_order_are_one_table_for_freshness(self):
        # They are separate SCORES (shuffle unlocks the green tiers) but either
        # is the child sitting down and doing that table.
        self._attempt(8, 'multiplication', days_ago=200, shuffled=True)
        self._attempt(8, 'multiplication', days_ago=5, shuffled=False)
        self.assertEqual(
            ttf.describe_map(self.student)[(8, 'multiplication')]['state'],
            ttf.FRESH,
        )

    def test_operations_age_separately(self):
        self._attempt(6, 'multiplication', days_ago=1)
        self._attempt(6, 'division', days_ago=120)
        described = ttf.describe_map(self.student)
        self.assertEqual(described[(6, 'multiplication')]['state'], ttf.FRESH)
        self.assertEqual(described[(6, 'division')]['state'], ttf.STALE)

    def test_legacy_rows_with_no_operation_count_as_multiplication(self):
        # The earliest attempts predate the operation column. Dropping them
        # would show "never practised" beside a result that is on the page.
        self._attempt(9, '', days_ago=10)
        described = ttf.describe_map(self.student)
        self.assertIn((9, 'multiplication'), described)
        self.assertEqual(described[(9, 'multiplication')]['days'], 10)

    def test_tables_needing_refresh_lists_each_table_once(self):
        self._attempt(3, 'multiplication', days_ago=200)
        self._attempt(3, 'division', days_ago=200)
        self._attempt(5, 'multiplication', days_ago=50)
        self._attempt(2, 'multiplication', days_ago=1)
        self.assertEqual(
            ttf.tables_needing_refresh(ttf.describe_map(self.student)),
            [3, 5],
        )

    def test_nothing_is_deleted_or_rewritten(self):
        # The guard on the original "expire after 3 months" idea: reading
        # freshness must leave every attempt, and every point, exactly as it
        # was — rebuild_points_ledger awards from the best attempt ever made.
        old = self._attempt(4, 'multiplication', days_ago=365, points=99.0)
        ttf.describe_map(self.student)
        old.refresh_from_db()
        self.assertEqual(old.points, 99.0)
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student).count(), 1)
