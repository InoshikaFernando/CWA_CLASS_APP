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

# The shared client issues requests.request(method, url, ...); patch there.
_REQUEST = 'cwa_classroom.jira_client.requests.request'


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

    def _fake_request(self, sprint_resp=None, issues_resp=None, issues_status=200):
        sprint_resp = sprint_resp if sprint_resp is not None else {'values': [self.SPRINT]}
        issues_resp = issues_resp if issues_resp is not None else self._issues_page()

        def _side_effect(method, url, **kwargs):
            if '/board/' in url and '/sprint' in url:
                return _resp(sprint_resp)
            if '/sprint/' in url and '/issue' in url:
                return _resp(issues_resp, status=issues_status)
            return _resp({}, status=404)
        return _side_effect

    @mock.patch(_REQUEST)
    def test_creates_sprint_and_snapshot(self, mock_request):
        mock_request.side_effect = self._fake_request()

        snapshot = services.sync_active_sprint()

        self.assertIsNotNone(snapshot)
        sprint = Sprint.objects.get(jira_sprint_id=100)
        self.assertEqual(sprint.name, 'Sprint 7')
        self.assertEqual(sprint.start_date, date(2026, 6, 1))
        # 8 remaining (in-progress) + 0 (unestimated); 5 done; committed = 13.
        self.assertEqual(snapshot.remaining_points, 8)
        self.assertEqual(snapshot.completed_points, 5)
        self.assertEqual(snapshot.total_points, 13)  # derived property
        self.assertEqual(sprint.committed_points, 13)
        self.assertTrue(sprint.baseline_captured)

    @mock.patch(_REQUEST)
    def test_idempotent_per_day(self, mock_request):
        mock_request.side_effect = self._fake_request()
        services.sync_active_sprint()
        services.sync_active_sprint()
        self.assertEqual(SprintSnapshot.objects.count(), 1)

    @mock.patch(_REQUEST)
    def test_committed_baseline_not_moved_by_scope_change(self, mock_request):
        mock_request.side_effect = self._fake_request()
        services.sync_active_sprint()

        # Second sync: scope grows (extra 10-pt issue), baseline must hold.
        bigger = self._issues_page()
        bigger['issues'].append(
            {'fields': {'customfield_10016': 10,
                        'status': {'statusCategory': {'key': 'new'}}}})
        mock_request.side_effect = self._fake_request(issues_resp=bigger)
        services.sync_active_sprint()

        sprint = Sprint.objects.get(jira_sprint_id=100)
        self.assertEqual(sprint.committed_points, 13)  # unchanged
        snap = sprint.snapshots.latest('snapshot_date')
        self.assertEqual(snap.total_points, 23)  # scope creep visible

    @mock.patch(_REQUEST)
    def test_partial_fetch_failure_records_no_snapshot(self, mock_request):
        # Issue page returns 500 -> shared client yields None -> sync aborts
        # rather than persisting a silently-truncated total.
        mock_request.side_effect = self._fake_request(issues_status=500)
        result = services.sync_active_sprint()
        self.assertIsNone(result)
        self.assertEqual(SprintSnapshot.objects.count(), 0)

    @mock.patch(_REQUEST)
    def test_zero_points_logs_misconfig_warning(self, mock_request):
        # Issues exist but none carry points (wrong story-points field).
        unpointed = {'total': 1, 'issues': [
            {'fields': {'customfield_10016': None,
                        'status': {'statusCategory': {'key': 'new'}}}}]}
        mock_request.side_effect = self._fake_request(issues_resp=unpointed)

        with self.assertLogs('sprints.services', level='WARNING') as cm:
            snapshot = services.sync_active_sprint()

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.total_points, 0)
        self.assertTrue(any('JIRA_STORY_POINTS_FIELD' in m for m in cm.output))
        # Zero total never locks the baseline.
        self.assertFalse(Sprint.objects.get(jira_sprint_id=100).baseline_captured)

    @mock.patch(_REQUEST)
    def test_no_active_sprint_returns_none(self, mock_request):
        mock_request.side_effect = self._fake_request(sprint_resp={'values': []})
        self.assertIsNone(services.sync_active_sprint())
        self.assertEqual(SprintSnapshot.objects.count(), 0)

    @override_settings(JIRA_BOARD_ID='')
    @mock.patch(_REQUEST)
    def test_unconfigured_is_noop(self, mock_request):
        self.assertIsNone(services.sync_active_sprint())
        mock_request.assert_not_called()


@override_settings(**JIRA_ENV)
class ParseDateTests(TestCase):
    @override_settings(USE_TZ=True, TIME_ZONE='UTC')
    def test_parses_utc_date(self):
        self.assertEqual(
            services._parse_date('2026-06-12T09:00:00.000Z'), date(2026, 6, 12))

    def test_none_for_blank(self):
        self.assertIsNone(services._parse_date(''))
        self.assertIsNone(services._parse_date(None))


@override_settings(**JIRA_ENV)
class SyncProjectBurndownTests(TestCase):
    def _search_page(self, issues, next_token=None):
        return {'issues': issues, 'nextPageToken': next_token,
                'isLast': next_token is None}

    @mock.patch(_REQUEST)
    def test_records_project_snapshot(self, mock_request):
        from sprints.models import ProjectSnapshot
        issues = [
            {'fields': {'customfield_10016': 5, 'status': {'statusCategory': {'key': 'done'}}}},
            {'fields': {'customfield_10016': 8, 'status': {'statusCategory': {'key': 'new'}}}},
            {'fields': {'customfield_10016': 3, 'status': {'statusCategory': {'key': 'indeterminate'}}}},
        ]
        mock_request.return_value = _resp(self._search_page(issues))

        snap = services.sync_project_burndown()

        self.assertIsNotNone(snap)
        self.assertEqual(snap.completed_points, 5)
        self.assertEqual(snap.remaining_points, 11)   # 8 + 3
        self.assertEqual(snap.total_points, 16)
        self.assertEqual(snap.open_issue_count, 2)
        self.assertEqual(ProjectSnapshot.objects.count(), 1)

    @mock.patch(_REQUEST)
    def test_paginates_via_next_token(self, mock_request):
        page1 = self._search_page(
            [{'fields': {'customfield_10016': 4, 'status': {'statusCategory': {'key': 'new'}}}}],
            next_token='tok2')
        page2 = self._search_page(
            [{'fields': {'customfield_10016': 6, 'status': {'statusCategory': {'key': 'new'}}}}])
        mock_request.side_effect = [_resp(page1), _resp(page2)]

        snap = services.sync_project_burndown()
        self.assertEqual(snap.remaining_points, 10)   # 4 + 6 across two pages
        self.assertEqual(mock_request.call_count, 2)

    @mock.patch(_REQUEST)
    def test_page_failure_records_nothing(self, mock_request):
        from sprints.models import ProjectSnapshot
        mock_request.return_value = _resp({}, status=500)
        self.assertIsNone(services.sync_project_burndown())
        self.assertEqual(ProjectSnapshot.objects.count(), 0)
