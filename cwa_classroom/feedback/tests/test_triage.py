"""Unit tests for the feedback triage dashboard (CPP-323).

Run with:
    pytest feedback/tests/test_triage.py -v
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from feedback.models import Feedback


class TriageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )

        cls.owner = CustomUser.objects.create_user(
            'tr_owner', 'tr_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(cls.admin_role)

        cls.teacher = CustomUser.objects.create_user(
            'tr_teacher', 'tr_teacher@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.teacher.roles.add(cls.teacher_role)

        cls.school = School.objects.create(
            name='TR School', slug='tr-school', admin=cls.owner,
        )

        cls.bug = Feedback.objects.create(
            submitted_by=cls.teacher, school=cls.school, role=Role.TEACHER,
            category=Feedback.CATEGORY_BUG, description='Bug here',
            status=Feedback.STATUS_NEW,
        )
        cls.feature = Feedback.objects.create(
            submitted_by=cls.teacher, school=cls.school, role=Role.TEACHER,
            category=Feedback.CATEGORY_FEATURE, description='A feature',
            status=Feedback.STATUS_TRIAGED, priority=Feedback.PRIORITY_HIGH,
        )
        cls.removed = Feedback.objects.create(
            submitted_by=cls.teacher, school=cls.school, role=Role.TEACHER,
            category=Feedback.CATEGORY_IMPROVEMENT, description='Gone',
        )
        cls.removed.soft_delete()

        cls.triage_url = reverse('feedback:triage')

    # ── Authorization ───────────────────────────────────────────────────
    def test_triage_requires_owner_role(self):
        # Anonymous → redirected to login.
        resp = self.client.get(self.triage_url)
        self.assertEqual(resp.status_code, 302)

        # Non-owner (teacher) → 403.
        self.client.force_login(self.teacher)
        resp = self.client.get(self.triage_url)
        self.assertEqual(resp.status_code, 403)

        # Owner (admin) → 200.
        self.client.force_login(self.owner)
        resp = self.client.get(self.triage_url)
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_excludes_soft_deleted(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.triage_url)
        items = list(resp.context['items'])
        self.assertIn(self.bug, items)
        self.assertIn(self.feature, items)
        self.assertNotIn(self.removed, items)

    # ── Filters ─────────────────────────────────────────────────────────
    def test_dashboard_filters_by_category_status(self):
        self.client.force_login(self.owner)

        resp = self.client.get(self.triage_url, {'category': Feedback.CATEGORY_BUG})
        items = list(resp.context['items'])
        self.assertEqual(items, [self.bug])

        resp = self.client.get(self.triage_url, {'status': Feedback.STATUS_TRIAGED})
        items = list(resp.context['items'])
        self.assertEqual(items, [self.feature])

        resp = self.client.get(self.triage_url, {'priority': Feedback.PRIORITY_HIGH})
        items = list(resp.context['items'])
        self.assertEqual(items, [self.feature])

    def test_new_items_listed_first(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.triage_url)
        items = list(resp.context['items'])
        self.assertEqual(items[0], self.bug)  # status=new sorts first

    # ── Inline update ───────────────────────────────────────────────────
    def test_set_priority_and_status_transition(self):
        self.client.force_login(self.owner)
        update_url = reverse('feedback:update', args=[self.bug.pk])
        resp = self.client.post(update_url, {
            'status': Feedback.STATUS_PLANNED,
            'priority': Feedback.PRIORITY_CRITICAL,
        })
        self.assertEqual(resp.status_code, 200)
        self.bug.refresh_from_db()
        self.assertEqual(self.bug.status, Feedback.STATUS_PLANNED)
        self.assertEqual(self.bug.priority, Feedback.PRIORITY_CRITICAL)

    def test_update_requires_owner(self):
        self.client.force_login(self.teacher)
        update_url = reverse('feedback:update', args=[self.bug.pk])
        resp = self.client.post(update_url, {'status': Feedback.STATUS_DONE})
        self.assertEqual(resp.status_code, 403)
        self.bug.refresh_from_db()
        self.assertEqual(self.bug.status, Feedback.STATUS_NEW)

    def test_update_missing_or_removed_returns_404(self):
        self.client.force_login(self.owner)
        # Soft-deleted item is not updatable.
        update_url = reverse('feedback:update', args=[self.removed.pk])
        resp = self.client.post(update_url, {'status': Feedback.STATUS_DONE})
        self.assertEqual(resp.status_code, 404)

        # Nonexistent pk.
        missing_url = reverse('feedback:update', args=[999999])
        resp = self.client.post(missing_url, {'status': Feedback.STATUS_DONE})
        self.assertEqual(resp.status_code, 404)

    def test_invalid_status_ignored(self):
        self.client.force_login(self.owner)
        update_url = reverse('feedback:update', args=[self.bug.pk])
        resp = self.client.post(update_url, {'status': 'bogus'})
        self.assertEqual(resp.status_code, 200)
        self.bug.refresh_from_db()
        self.assertEqual(self.bug.status, Feedback.STATUS_NEW)
