"""Tests for feedback screenshot attachments (CPP-324).

Covers the capture view (uploading / validating screenshots), the service that
pushes them onto the Jira issue, and the shared Jira attachment client. All
network is mocked — no real HTTP call is made, and uploads write to a temp
MEDIA_ROOT so nothing touches real storage.

Run with:
    pytest feedback/tests/test_screenshots.py -v
"""
import io
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolStudent
from cwa_classroom import jira_client
from feedback import services
from feedback.models import Feedback, FeedbackImage

_MEDIA = tempfile.mkdtemp()


def _png(name='shot.png', color='red'):
    """A tiny valid PNG wrapped as an uploaded file."""
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), color).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=_MEDIA)
class SubmitWithScreenshotsTests(TestCase):
    """The capture view stores uploaded screenshots and validates them."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'ss_owner', 'ss_owner@example.com', 'pass1!',
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.student = CustomUser.objects.create_user(
            'ss_student', 'ss_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.student.roles.add(cls.student_role)
        cls.school = School.objects.create(
            name='SS School', slug='ss-school', admin=cls.owner,
        )
        SchoolStudent.objects.get_or_create(school=cls.school, student=cls.student)

    def setUp(self):
        self.url = reverse('feedback:submit')
        self.client.force_login(self.student)

    @mock.patch('taskqueue.services.enqueue_task')
    def test_screenshots_are_saved(self, _enqueue):
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'description': 'Broken question.',
            'screenshots': [_png('a.png'), _png('b.png', 'blue')],
        })
        self.assertEqual(resp.status_code, 200)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.images.count(), 2)

    @mock.patch('taskqueue.services.enqueue_task')
    def test_submission_without_screenshots_still_works(self, _enqueue):
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'description': 'No image here.',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Feedback.objects.get().images.count(), 0)

    @mock.patch('taskqueue.services.enqueue_task')
    def test_non_image_upload_is_rejected(self, _enqueue):
        bad = SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain')
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'description': 'Tried to attach a text file.',
            'screenshots': [bad],
        })
        self.assertEqual(resp.status_code, 400)
        # Nothing persisted — the error is surfaced, not swallowed.
        self.assertEqual(Feedback.objects.count(), 0)
        self.assertEqual(FeedbackImage.objects.count(), 0)
        self.assertContains(resp, 'is not an image', status_code=400)

    @mock.patch('taskqueue.services.enqueue_task')
    def test_too_many_screenshots_rejected(self, _enqueue):
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'description': 'Six images.',
            'screenshots': [_png(f'{i}.png') for i in range(6)],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Feedback.objects.count(), 0)
        self.assertContains(resp, 'at most 5 screenshots', status_code=400)

    @mock.patch('taskqueue.services.enqueue_task')
    def test_oversized_screenshot_rejected(self, _enqueue):
        big = SimpleUploadedFile(
            'huge.png', b'x' * (10 * 1024 * 1024 + 1), content_type='image/png',
        )
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG,
            'description': 'Massive file.',
            'screenshots': [big],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Feedback.objects.count(), 0)
        self.assertContains(resp, 'under 10 MB', status_code=400)


@override_settings(
    MEDIA_ROOT=_MEDIA,
    JIRA_BASE_URL='https://example.atlassian.net',
    JIRA_USER_EMAIL='svc@example.com',
    JIRA_API_TOKEN='token123',
    JIRA_PROJECT_KEY='CPP',
    FEEDBACK_DISCORD_WEBHOOK='',
)
class AttachFeedbackImagesTests(TestCase):
    """report_feedback_bug pushes stored screenshots onto the Jira issue."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'af_owner', 'af_owner@example.com', 'pass1!',
        )
        cls.user = CustomUser.objects.create_user(
            'af_user', 'af_reporter@example.com', 'pass1!',
        )

    def _feedback_with_images(self, n=2):
        feedback = Feedback.objects.create(
            submitted_by=self.user,
            category=Feedback.CATEGORY_BUG,
            title='Broken',
            description='Boom.',
        )
        for i in range(n):
            FeedbackImage.objects.create(feedback=feedback, image=_png(f's{i}.png'))
        return feedback

    @mock.patch('feedback.services.requests.post')  # Discord (disabled)
    @mock.patch('cwa_classroom.jira_client.upload_attachment')
    @mock.patch('cwa_classroom.jira_client.requests.request')
    def test_each_image_uploaded_to_jira(self, mock_request, mock_upload, _discord):
        mock_request.return_value = mock.Mock(
            status_code=201, json=mock.Mock(return_value={'key': 'CPP-321'}),
        )
        feedback = self._feedback_with_images(n=2)
        services.report_feedback_bug(feedback)

        feedback.refresh_from_db()
        self.assertEqual(feedback.jira_key, 'CPP-321')
        # One attachment call per stored screenshot, all to the new issue key.
        self.assertEqual(mock_upload.call_count, 2)
        for call in mock_upload.call_args_list:
            self.assertEqual(call.args[0], 'CPP-321')

    @mock.patch('feedback.services.requests.post')
    @mock.patch('cwa_classroom.jira_client.upload_attachment')
    @mock.patch('cwa_classroom.jira_client.requests.request')
    def test_no_upload_when_jira_creation_fails(self, mock_request, mock_upload, _discord):
        # Issue creation returns non-2xx → no key → nothing to attach to.
        mock_request.return_value = mock.Mock(status_code=500, text='boom')
        feedback = self._feedback_with_images(n=1)
        services.report_feedback_bug(feedback)
        mock_upload.assert_not_called()

    @mock.patch('feedback.services.requests.post')
    @mock.patch('cwa_classroom.jira_client.upload_attachment', side_effect=Exception('nope'))
    @mock.patch('cwa_classroom.jira_client.requests.request')
    def test_upload_failure_does_not_crash(self, mock_request, _upload, _discord):
        # A raising upload must not bubble out of the worker task.
        mock_request.return_value = mock.Mock(
            status_code=201, json=mock.Mock(return_value={'key': 'CPP-999'}),
        )
        feedback = self._feedback_with_images(n=1)
        # attach_feedback_images swallows per-image failures; assert it logs.
        with self.assertLogs('feedback.services', level='ERROR'):
            services.report_feedback_bug(feedback)
        feedback.refresh_from_db()
        self.assertEqual(feedback.jira_key, 'CPP-999')


class UploadAttachmentClientTests(TestCase):
    """The shared jira_client.upload_attachment contract."""

    @override_settings(JIRA_BASE_URL='', JIRA_USER_EMAIL='', JIRA_API_TOKEN='')
    @mock.patch('cwa_classroom.jira_client.requests.post')
    def test_unconfigured_returns_none_and_logs(self, mock_post):
        with self.assertLogs('cwa_classroom.jira_client', level='WARNING'):
            result = jira_client.upload_attachment('CPP-1', 'a.png', b'x', 'image/png')
        self.assertIsNone(result)
        mock_post.assert_not_called()

    @override_settings(
        JIRA_BASE_URL='https://example.atlassian.net',
        JIRA_USER_EMAIL='svc@example.com',
        JIRA_API_TOKEN='token123',
    )
    @mock.patch('cwa_classroom.jira_client.requests.post')
    def test_configured_posts_multipart_with_no_check_header(self, mock_post):
        mock_post.return_value = mock.Mock(
            status_code=200, json=mock.Mock(return_value=[{'id': '1'}]),
        )
        result = jira_client.upload_attachment('CPP-1', 'a.png', b'bytes', 'image/png')
        self.assertEqual(result, [{'id': '1'}])

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['X-Atlassian-Token'], 'no-check')
        self.assertEqual(kwargs['auth'], ('svc@example.com', 'token123'))
        self.assertIn('file', kwargs['files'])
        self.assertEqual(kwargs['files']['file'][0], 'a.png')

    @override_settings(
        JIRA_BASE_URL='https://example.atlassian.net',
        JIRA_USER_EMAIL='svc@example.com',
        JIRA_API_TOKEN='token123',
    )
    @mock.patch('cwa_classroom.jira_client.requests.post')
    def test_non_2xx_returns_none_and_logs_error(self, mock_post):
        mock_post.return_value = mock.Mock(status_code=413, text='too big')
        with self.assertLogs('cwa_classroom.jira_client', level='ERROR'):
            result = jira_client.upload_attachment('CPP-1', 'a.png', b'x', 'image/png')
        self.assertIsNone(result)
