"""Tests for the pure burndown-series computation."""
from datetime import date

from django.test import TestCase

from sprints.burndown import build_burndown_series
from sprints.models import Sprint, SprintSnapshot


class BuildBurndownSeriesTests(TestCase):
    def _sprint(self, **kwargs):
        defaults = dict(
            jira_sprint_id=1, name='Sprint 1',
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
            committed_points=20,
        )
        defaults.update(kwargs)
        return Sprint.objects.create(**defaults)

    def test_ideal_line_runs_from_committed_to_zero(self):
        sprint = self._sprint()  # 5 days (1st–5th inclusive)
        series = build_burndown_series(sprint)

        self.assertEqual(len(series['labels']), 5)
        self.assertEqual(series['labels'][0], '2026-06-01')
        self.assertEqual(series['ideal'][0], 20)
        self.assertEqual(series['ideal'][-1], 0)
        self.assertEqual(series['committed'], 20)

    def test_actual_uses_snapshots_and_gaps_for_missing_days(self):
        sprint = self._sprint()
        SprintSnapshot.objects.create(
            sprint=sprint, snapshot_date=date(2026, 6, 1),
            remaining_points=20, completed_points=0)
        SprintSnapshot.objects.create(
            sprint=sprint, snapshot_date=date(2026, 6, 3),
            remaining_points=12, completed_points=8)

        series = build_burndown_series(sprint)

        # Days with snapshots carry values; days without are None (chart gap).
        self.assertEqual(series['actual'][0], 20)
        self.assertIsNone(series['actual'][1])
        self.assertEqual(series['actual'][2], 12)
        self.assertIsNone(series['actual'][4])

    def test_falls_back_to_snapshot_dates_without_sprint_dates(self):
        sprint = self._sprint(start_date=None, end_date=None)
        SprintSnapshot.objects.create(
            sprint=sprint, snapshot_date=date(2026, 6, 2),
            remaining_points=8, completed_points=12)

        series = build_burndown_series(sprint)
        self.assertEqual(series['labels'], ['2026-06-02'])
        self.assertEqual(series['actual'], [8])
