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


class BuildProjectSeriesTests(TestCase):
    def test_series_from_snapshots(self):
        from sprints.burndown import build_project_series
        from sprints.models import ProjectSnapshot
        ProjectSnapshot.objects.create(
            snapshot_date=date(2026, 6, 1), remaining_points=40,
            completed_points=10, open_issue_count=12)
        ProjectSnapshot.objects.create(
            snapshot_date=date(2026, 6, 2), remaining_points=35,
            completed_points=15, open_issue_count=10)

        series = build_project_series(
            ProjectSnapshot.objects.order_by('snapshot_date'))

        self.assertEqual(series['labels'], ['2026-06-01', '2026-06-02'])
        self.assertEqual(series['remaining'], [40, 35])
        self.assertEqual(series['total'], [50, 50])  # remaining + completed
        self.assertEqual(series['open_counts'], [12, 10])


class ReconstructProjectHistoryTests(TestCase):
    def test_replays_created_and_resolved_dates(self):
        from sprints.burndown import reconstruct_project_history
        issues = [
            # opened 6/1 (5pts), resolved 6/3
            {'created': date(2026, 6, 1), 'resolved': date(2026, 6, 3), 'points': 5},
            # opened 6/2 (8pts), still open
            {'created': date(2026, 6, 2), 'resolved': None, 'points': 8},
        ]
        rows = reconstruct_project_history(issues, date(2026, 6, 4))

        # Days 6/1..6/4 inclusive.
        self.assertEqual([r['date'] for r in rows],
                         [date(2026, 6, d) for d in (1, 2, 3, 4)])
        # 6/1: only issue A open → total 5, remaining 5
        self.assertEqual((rows[0]['total'], rows[0]['remaining'], rows[0]['open_count']), (5, 5, 1))
        # 6/2: A + B opened → total 13, remaining 13, 2 open
        self.assertEqual((rows[1]['total'], rows[1]['remaining'], rows[1]['open_count']), (13, 13, 2))
        # 6/3: A resolved → completed 5, remaining 8, 1 open
        self.assertEqual((rows[2]['completed'], rows[2]['remaining'], rows[2]['open_count']), (5, 8, 1))
        # 6/4: unchanged from 6/3
        self.assertEqual((rows[3]['remaining'], rows[3]['open_count']), (8, 1))

    def test_empty_when_no_created_dates(self):
        from sprints.burndown import reconstruct_project_history
        self.assertEqual(reconstruct_project_history([], date(2026, 6, 4)), [])
        self.assertEqual(
            reconstruct_project_history([{'created': None, 'resolved': None, 'points': 3}],
                                        date(2026, 6, 4)), [])
