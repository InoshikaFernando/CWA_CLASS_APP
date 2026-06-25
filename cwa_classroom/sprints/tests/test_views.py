"""Access-control and rendering tests for the burndown view."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from sprints.models import ProjectSnapshot


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

    def test_non_superuser_redirected(self):
        self.client.force_login(self.student)
        resp = self.client.get(self.url)
        # SuperuserRequiredMixin redirects non-superusers (not a 403).
        self.assertEqual(resp.status_code, 302)

    def test_owner_sees_empty_state_without_data(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No project data yet')

    def test_owner_sees_chart_with_data(self):
        ProjectSnapshot.objects.create(
            snapshot_date=date(2026, 6, 1),
            remaining_points=40, completed_points=10, open_issue_count=12)
        ProjectSnapshot.objects.create(
            snapshot_date=date(2026, 6, 2),
            remaining_points=35, completed_points=15, open_issue_count=10)

        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'burndownChart')
        self.assertContains(resp, 'Project Burndown')
        # Freshness indicator reflects the latest snapshot's sync time.
        self.assertContains(resp, 'Last synced from Jira')
