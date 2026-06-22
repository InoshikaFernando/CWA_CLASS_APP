"""CPP-307b: notifications dropdown view."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from taskqueue.models import BackgroundTask


class NotificationsDropdownTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('nu', 'nu@test.internal', 'pw1!')
        cls.other = CustomUser.objects.create_user('no', 'no@test.internal', 'pw1!')
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'})
        cls.user.roles.add(admin_role)
        cls.school = School.objects.create(name='N School', slug='n-school', admin=cls.user)

    def _task(self, user, rq_job_id, status=BackgroundTask.PENDING, **overrides):
        return BackgroundTask.objects.create(
            school=self.school, created_by=user, task_type='ai_import_pdf',
            rq_job_id=rq_job_id, status=status, **overrides)

    def test_requires_login(self):
        resp = self.client.get(reverse('taskqueue:notifications'))
        self.assertIn(resp.status_code, (302, 301))

    def test_lists_only_own_tasks(self):
        self._task(self.user, 'mine-1', status=BackgroundTask.DONE,
                   result_data={'session_id': 5})
        self._task(self.other, 'theirs-1')
        self.client.force_login(self.user)
        resp = self.client.get(reverse('taskqueue:notifications'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'PDF question import')
        # Only one item (the other user's task excluded)
        self.assertEqual(resp.content.decode().count('PDF question import'), 1)

    def test_active_task_shows_dot(self):
        self._task(self.user, 'active-1', status=BackgroundTask.RUNNING)
        self.client.force_login(self.user)
        resp = self.client.get(reverse('taskqueue:notifications'))
        # OOB dot rendered visible (block) when a task is active
        self.assertContains(resp, 'id="notif-dot"')
        self.assertContains(resp, 'block absolute')

    def test_done_task_links_to_preview(self):
        self._task(self.user, 'done-1', status=BackgroundTask.DONE,
                   result_data={'session_id': 9})
        self.client.force_login(self.user)
        resp = self.client.get(reverse('taskqueue:notifications'))
        self.assertContains(resp, reverse('ai_import:preview', args=[9]))

    def test_empty_state(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('taskqueue:notifications'))
        self.assertContains(resp, 'No background tasks yet')
