"""Tests for the Jira Agile sync. All network is mocked — no real HTTP."""
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings

from sprints import services
from sprints.models import Sprint, SprintSnapshot

JIRA_ENV = dict(
    JIRA_BASE_URL='https://example.atlassian.net',
    JIRA_USER_EMAIL='bot@example.com',
    JIRA_API_TOKEN='token',
    JIRA_BOARD_ID='42',
    JIRA_STORY_POINTS_FIELD='customfield_10016',
)


def _resp(json_data, status=200):
    m = mock.Mock()
    m.status_code = status
    m.json.return_value = json_data
    m.text = str(json_data)
    return m


@override_settings(**JIRA_ENV)
class SyncActiveSprintTests(TestCase):
    SPRINT = {
        'id': 100, 'name': 'Sprint 7', 'state': 'active',
        'startDate': '2026-06-01T09:00:00.000Z',
        'endDate': '2026-06-12T09:00:00.000Z', 'goal': 'Ship burndown',
    }

    def _issues_page(self):
        return {
            'total': 3, 'issues': [
                {'fields': {'customfield_10016': 5,
                            'status': {'statusCategory': {'key': 'done'}}}},
                {'fields': {'customfield_10016': 8,
                            'status': {'statusCategory': {'key': 'indeterminate'}}}},
                {'fields': {'customfield_10016': None,
                            'status': {'statusCategory': {'key': 'new'}}}},
            ],
        }

    def _fake_get(self, sprint_resp=None, issues_resp=None):
        sprint_resp = sprint_resp if sprint_resp is not None else {'values': [self.SPRINT]}
        issues_resp = issues_resp if issues_resp is not None else self._issues_page()

        def _side_effect(url, **kwargs):
            if '/board/' in url and '/sprint' in url:
                return _resp(sprint_resp)
            if '/sprint/' in url and '/issue' in url:
                return _resp(issues_resp)
            return _resp({}, status=404)
        return _side_effect

    @mock.patch('sprints.services.requests.get')
    def test_creates_sprint_and_snapshot(self, mock_get):
        mock_get.side_effect = self._fake_get()

        snapshot = services.sync_active_sprint()

        self.assertIsNotNone(snapshot)
        sprint = Sprint.objects.get(jira_sprint_id=100)
        self.assertEqual(sprint.name, 'Sprint 7')
        self.assertEqual(sprint.start_date, date(2026, 6, 1))
        # 8 remaining (in-progress) + 0 (unestimated); 5 done; committed = 13.
        self.assertEqual(snapshot.remaining_points, 8)
        self.assertEqual(snapshot.completed_points, 5)
        self.assertEqual(snapshot.total_points, 13)
        self.assertEqual(sprint.committed_points, 13)

    @mock.patch('sprints.services.requests.get')
    def test_idempotent_per_day(self, mock_get):
        mock_get.side_effect = self._fake_get()
        services.sync_active_sprint()
        services.sync_active_sprint()
        self.assertEqual(SprintSnapshot.objects.count(), 1)

    @mock.patch('sprints.services.requests.get')
    def test_committed_baseline_not_moved_by_scope_change(self, mock_get):
        mock_get.side_effect = self._fake_get()
        services.sync_active_sprint()

        # Second sync: scope grows (extra 10-pt issue), baseline must hold.
        bigger = self._issues_page()
        bigger['total'] = 4
        bigger['issues'].append(
            {'fields': {'customfield_10016': 10,
                        'status': {'statusCategory': {'key': 'new'}}}})
        mock_get.side_effect = self._fake_get(issues_resp=bigger)
        services.sync_active_sprint()

        sprint = Sprint.objects.get(jira_sprint_id=100)
        self.assertEqual(sprint.committed_points, 13)  # unchanged
        snap = sprint.snapshots.latest('snapshot_date')
        self.assertEqual(snap.total_points, 23)  # scope creep visible

    @mock.patch('sprints.services.requests.get')
    def test_no_active_sprint_returns_none(self, mock_get):
        mock_get.side_effect = self._fake_get(sprint_resp={'values': []})
        self.assertIsNone(services.sync_active_sprint())
        self.assertEqual(SprintSnapshot.objects.count(), 0)

    @override_settings(JIRA_BOARD_ID='')
    @mock.patch('sprints.services.requests.get')
    def test_unconfigured_is_noop(self, mock_get):
        self.assertIsNone(services.sync_active_sprint())
        mock_get.assert_not_called()
