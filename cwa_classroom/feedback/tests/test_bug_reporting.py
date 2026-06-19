"""Tests for bug-feedback auto-filing to Jira + Discord (CPP-321).

All network is mocked — these tests never make a real HTTP call.

Run with:
    pytest feedback/tests/test_bug_reporting.py -v
"""
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolStudent
from feedback import services
from feedback.models import Feedback


class SubmitBugTriggersReportingTests(TestCase):
    """The capture view enqueues the Jira/Discord task only for bugs."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'bug_owner', 'bug_owner@example.com', 'pass1!',
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.student = CustomUser.objects.create_user(
            'bug_student', 'bug_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.student.roles.add(cls.student_role)
        cls.school = School.objects.create(
            name='Bug School', slug='bug-school', admin=cls.owner,
        )
        SchoolStudent.objects.get_or_create(school=cls.school, student=cls.student)

    def setUp(self):
        self.url = reverse('feedback:submit')
        self.client.force_login(self.student)

    @mock.patch('taskqueue.services.enqueue_task')
    def test_bug_submission_enqueues_task(self, mock_enqueue):
        # The view does `from taskqueue.services import enqueue_task` at call
        # time, so patching the source module is what intercepts it.
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'title': 'Crash on save',
            'description': 'It crashes.',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(mock_enqueue.called)

        feedback = Feedback.objects.get()
        _, kwargs = mock_enqueue.call_args
        self.assertEqual(kwargs['task_type'], 'feedback_bug_report')
        self.assertEqual(kwargs['args'], [feedback.id])

    @mock.patch('taskqueue.services.enqueue_task')
    def test_non_bug_submission_does_not_enqueue(self, mock_enqueue):
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_FEATURE,
            'title': 'Add dark mode',
            'description': 'Please.',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(mock_enqueue.called)

    @mock.patch('taskqueue.services.enqueue_task', side_effect=Exception('queue down'))
    def test_queue_unavailable_does_not_break_submission(self, mock_enqueue):
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'title': 'Crash',
            'description': 'Boom.',
        })
        # Submission still succeeds even though enqueue blew up.
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Feedback.objects.count(), 1)


@override_settings(
    JIRA_BASE_URL='', JIRA_USER_EMAIL='', JIRA_API_TOKEN='',
    JIRA_PROJECT_KEY='CPP', FEEDBACK_DISCORD_WEBHOOK='',
)
class CreateJiraBugUnconfiguredTests(TestCase):
    @mock.patch('feedback.services.requests.post')
    def test_returns_none_and_logs_when_unconfigured(self, mock_post):
        with self.assertLogs('feedback.services', level='WARNING') as cm:
            result = services.create_jira_bug(
                summary='x', description='y',
            )
        self.assertIsNone(result)
        # No network call attempted.
        mock_post.assert_not_called()
        self.assertTrue(
            any('Jira not configured' in m for m in cm.output),
        )


@override_settings(
    JIRA_BASE_URL='https://example.atlassian.net',
    JIRA_USER_EMAIL='svc@example.com',
    JIRA_API_TOKEN='token123',
    JIRA_PROJECT_KEY='CPP',
    FEEDBACK_DISCORD_WEBHOOK='',
)
class CreateJiraBugConfiguredTests(TestCase):
    @mock.patch('feedback.services.requests.post')
    def test_builds_adf_and_returns_key(self, mock_post):
        mock_post.return_value = mock.Mock(
            status_code=201, json=mock.Mock(return_value={'key': 'CPP-999'}),
        )
        key = services.create_jira_bug(
            summary='Bug summary', description='Bug body', labels=['feedback'],
        )
        self.assertEqual(key, 'CPP-999')

        _, kwargs = mock_post.call_args
        fields = kwargs['json']['fields']
        self.assertEqual(fields['project']['key'], 'CPP')
        self.assertEqual(fields['issuetype']['name'], 'Bug')
        self.assertEqual(fields['labels'], ['feedback'])
        # description is ADF (a doc node), not a bare string.
        self.assertEqual(fields['description']['type'], 'doc')
        self.assertEqual(
            fields['description']['content'][0]['content'][0]['text'],
            'Bug body',
        )
        # HTTP basic auth uses email:token.
        self.assertEqual(kwargs['auth'], ('svc@example.com', 'token123'))

    @mock.patch('feedback.services.requests.post')
    def test_non_2xx_returns_none_and_logs_error(self, mock_post):
        mock_post.return_value = mock.Mock(status_code=400, text='bad request')
        with self.assertLogs('feedback.services', level='ERROR') as cm:
            key = services.create_jira_bug(summary='x', description='y')
        self.assertIsNone(key)
        self.assertTrue(any('400' in m for m in cm.output))


@override_settings(
    JIRA_BASE_URL='https://example.atlassian.net',
    JIRA_USER_EMAIL='svc@example.com',
    JIRA_API_TOKEN='token123',
    JIRA_PROJECT_KEY='CPP',
    FEEDBACK_DISCORD_WEBHOOK='https://discord.example/webhook',
)
class ReportFeedbackBugTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'rfb_owner', 'rfb_owner@example.com', 'pass1!',
        )
        cls.user = CustomUser.objects.create_user(
            'rfb_user', 'reporter@example.com', 'pass1!',
        )
        cls.school = School.objects.create(
            name='RFB School', slug='rfb-school', admin=cls.owner,
        )

    def _make_feedback(self, **kwargs):
        defaults = dict(
            submitted_by=self.user,
            category=Feedback.CATEGORY_BUG,
            title='Login broken',
            description='Cannot log in.',
            school=self.school,
        )
        defaults.update(kwargs)
        return Feedback.objects.create(**defaults)

    @mock.patch('feedback.services.requests.post')
    def test_files_jira_and_saves_key_then_posts_discord(self, mock_post):
        # First call: Jira issue creation. Second: Discord webhook.
        jira_resp = mock.Mock(
            status_code=201, json=mock.Mock(return_value={'key': 'CPP-123'}),
        )
        discord_resp = mock.Mock(status_code=204, text='')
        mock_post.side_effect = [jira_resp, discord_resp]

        feedback = self._make_feedback()
        services.report_feedback_bug(feedback)

        feedback.refresh_from_db()
        self.assertEqual(feedback.jira_key, 'CPP-123')
        self.assertEqual(mock_post.call_count, 2)
        # Discord content references the Jira browse URL and reporter.
        _, discord_kwargs = mock_post.call_args
        content = discord_kwargs['json']['content']
        self.assertIn('CPP-123', content)
        self.assertIn('reporter@example.com', content)

    @mock.patch('feedback.services.requests.post')
    def test_idempotent_when_jira_key_already_set(self, mock_post):
        feedback = self._make_feedback(jira_key='CPP-555')
        services.report_feedback_bug(feedback)
        # Already filed → no Jira/Discord calls at all.
        mock_post.assert_not_called()
        feedback.refresh_from_db()
        self.assertEqual(feedback.jira_key, 'CPP-555')
