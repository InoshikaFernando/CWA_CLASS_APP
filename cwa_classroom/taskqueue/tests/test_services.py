from unittest.mock import MagicMock, patch

from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import School
from taskqueue.models import BackgroundTask
from taskqueue.services import enqueue_task, on_task_failure, on_task_success


def _dummy_task():
    return {'result': 'ok'}


class EnqueueTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            'eq_admin', 'eq_admin@example.com', 'pass1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin.roles.add(admin_role)
        cls.school = School.objects.create(
            name='EQ Test School', slug='eq-test-school', admin=cls.admin,
        )

    @patch('taskqueue.services.django_rq.get_queue')
    def test_enqueue_creates_background_task(self, mock_get_queue):
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = 'rq-job-123'
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        task, job = enqueue_task(
            school=self.school,
            user=self.admin,
            task_type='pdf_classify',
            func=_dummy_task,
        )

        self.assertEqual(task.status, BackgroundTask.PENDING)
        self.assertEqual(task.rq_job_id, 'rq-job-123')
        self.assertEqual(task.school, self.school)
        self.assertEqual(task.created_by, self.admin)
        self.assertEqual(task.task_type, 'pdf_classify')

    @patch('taskqueue.services.django_rq.get_queue')
    def test_enqueue_records_job_id(self, mock_get_queue):
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = 'rq-job-456'
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        task, job = enqueue_task(
            school=self.school,
            user=self.admin,
            task_type='ai_grade',
            func=_dummy_task,
        )

        self.assertEqual(BackgroundTask.objects.get(pk=task.pk).rq_job_id, 'rq-job-456')

    @patch('taskqueue.services.django_rq.get_queue')
    def test_enqueue_respects_queue_priority(self, mock_get_queue):
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = 'rq-job-high'
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        enqueue_task(
            school=self.school,
            user=self.admin,
            task_type='ai_grade',
            func=_dummy_task,
            queue='high',
        )

        mock_get_queue.assert_called_once_with('high')


class CallbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            'cb_admin', 'cb_admin@example.com', 'pass1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin.roles.add(admin_role)
        cls.school = School.objects.create(
            name='CB Test School', slug='cb-test-school', admin=cls.admin,
        )

    def _make_task(self, rq_job_id='cb-job-001', **overrides):
        defaults = dict(
            school=self.school,
            task_type='pdf_classify',
            rq_job_id=rq_job_id,
            created_by=self.admin,
        )
        defaults.update(overrides)
        return BackgroundTask.objects.create(**defaults)

    def test_success_callback_updates_status_to_done(self):
        task = self._make_task(rq_job_id='success-job-1')
        mock_job = MagicMock()
        mock_job.id = 'success-job-1'

        on_task_success(mock_job, None, {'pages': 5})

        task.refresh_from_db()
        self.assertEqual(task.status, BackgroundTask.DONE)
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.result_data, {'pages': 5})

    def test_failure_callback_updates_status_and_retries(self):
        task = self._make_task(rq_job_id='fail-job-1')
        mock_job = MagicMock()
        mock_job.id = 'fail-job-1'

        on_task_failure(mock_job, None, ValueError, ValueError('API timeout'), None)

        task.refresh_from_db()
        # First failure triggers retry — status back to PENDING
        self.assertEqual(task.status, BackgroundTask.PENDING)
        self.assertEqual(task.retry_count, 1)
        mock_job.requeue.assert_called_once()

    def test_failure_after_max_retries_stays_failed(self):
        task = self._make_task(rq_job_id='maxretry-job-1')
        task.retry_count = BackgroundTask.MAX_RETRIES
        task.save(update_fields=['retry_count'])

        mock_job = MagicMock()
        mock_job.id = 'maxretry-job-1'

        on_task_failure(mock_job, None, RuntimeError, RuntimeError('fatal'), None)

        task.refresh_from_db()
        self.assertEqual(task.status, BackgroundTask.FAILED)
        self.assertIn('RuntimeError', task.error_message)
        self.assertIsNotNone(task.completed_at)
        mock_job.requeue.assert_not_called()

    def test_retry_increments_count(self):
        task = self._make_task(rq_job_id='retry-inc-job')
        mock_job = MagicMock()
        mock_job.id = 'retry-inc-job'

        on_task_failure(mock_job, None, ValueError, ValueError('err'), None)
        task.refresh_from_db()
        self.assertEqual(task.retry_count, 1)

        on_task_failure(mock_job, None, ValueError, ValueError('err'), None)
        task.refresh_from_db()
        self.assertEqual(task.retry_count, 2)

    def test_success_callback_missing_task_does_not_crash(self):
        mock_job = MagicMock()
        mock_job.id = 'nonexistent-job'
        on_task_success(mock_job, None, None)

    def test_failure_callback_missing_task_does_not_crash(self):
        mock_job = MagicMock()
        mock_job.id = 'nonexistent-job-2'
        on_task_failure(mock_job, None, ValueError, ValueError('err'), None)
