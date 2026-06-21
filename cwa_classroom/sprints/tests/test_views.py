"""Access-control and rendering tests for the burndown view."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from sprints.models import Sprint, SprintSnapshot


class BurndownViewAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'sprint_owner', 'sprint_owner@example.com', 'pass1!')
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'})
        cls.student = CustomUser.objects.create_user(
            'sprint_student', 'sprint_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.student.roles.add(cls.student_role)
        cls.url = reverse('sprints:burndown')

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp.url)

    def test_non_owner_forbidden(self):
        self.client.force_login(self.student)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_owner_sees_empty_state_without_data(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No sprint data yet')

    def test_owner_sees_chart_with_data(self):
        sprint = Sprint.objects.create(
            jira_sprint_id=1, name='Sprint 1', state=Sprint.STATE_ACTIVE,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
            committed_points=20)
        SprintSnapshot.objects.create(
            sprint=sprint, snapshot_date=date(2026, 6, 1),
            remaining_points=20, total_points=20)

        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'burndownChart')
        self.assertContains(resp, 'Sprint 1')
