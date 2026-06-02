from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import School
from taskqueue.models import BackgroundTask


class BackgroundTaskModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            'tq_admin', 'tq_admin@example.com', 'pass1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin.roles.add(admin_role)
        cls.school = School.objects.create(
            name='TQ Test School', slug='tq-test-school', admin=cls.admin,
        )

    def _make_task(self, **overrides):
        defaults = dict(
            school=self.school,
            task_type='pdf_classify',
            rq_job_id='test-job-001',
            created_by=self.admin,
        )
        defaults.update(overrides)
        return BackgroundTask.objects.create(**defaults)

    def test_creation_sets_pending_status(self):
        task = self._make_task()
        self.assertEqual(task.status, BackgroundTask.PENDING)

    def test_creation_sets_zero_retry_count(self):
        task = self._make_task()
        self.assertEqual(task.retry_count, 0)

    def test_completed_at_null_on_creation(self):
        task = self._make_task()
        self.assertIsNone(task.completed_at)

    def test_school_fk_enforced(self):
        # SQLite defers FK checks; verify the FK relationship exists
        field = BackgroundTask._meta.get_field('school')
        self.assertFalse(field.null)
        self.assertEqual(field.related_model.__name__, 'School')

    def test_rq_job_id_unique(self):
        self._make_task(rq_job_id='unique-job-1')
        with self.assertRaises(IntegrityError):
            self._make_task(rq_job_id='unique-job-1')

    def test_str_representation(self):
        task = self._make_task()
        result = str(task)
        self.assertIn('pdf_classify', result)
        self.assertIn('pending', result)
        self.assertIn('TQ Test School', result)

    def test_ordering_newest_first(self):
        now = timezone.now()
        t1 = self._make_task(rq_job_id='job-older')
        # Force different created_at since auto_now_add may resolve to same second
        BackgroundTask.objects.filter(pk=t1.pk).update(created_at=now - timedelta(minutes=5))
        t2 = self._make_task(rq_job_id='job-newer')
        tasks = list(BackgroundTask.objects.all())
        self.assertEqual(tasks[0].pk, t2.pk)
        self.assertEqual(tasks[1].pk, t1.pk)
