"""
accounts/tests_audit_logging.py — Audit logging tests for auth events (CPP-271).
"""
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from audit.models import AuditLog

User = get_user_model()


class TestLogoutAuditLog(TestCase):
    """Logout event logs an audit entry with category 'auth'."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='logoutuser', password='pass1234', email='lo@test.com',
        )

    def setUp(self):
        self.client = Client()
        AuditLog.objects.all().delete()

    def test_logout_logs_event(self):
        self.client.login(username='logoutuser', password='pass1234')
        resp = self.client.post(reverse('logout'))
        # LogoutView redirects by default
        self.assertIn(resp.status_code, [200, 302])

        log = AuditLog.objects.filter(action='logout').first()
        self.assertIsNotNone(log, 'No logout audit log found')
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.category, 'auth')

    def test_logout_includes_session_duration(self):
        # Login via the view to set login_at in session
        self.client.post(reverse('login'), {
            'username': 'logoutuser', 'password': 'pass1234',
        })

        # Manually set login_at to 60 seconds ago to simulate duration
        session = self.client.session
        session['login_at'] = time.time() - 60
        session.save()

        self.client.post(reverse('logout'))

        log = AuditLog.objects.filter(action='logout').first()
        self.assertIsNotNone(log)
        self.assertIn('session_duration_seconds', log.detail)
        self.assertGreaterEqual(log.detail['session_duration_seconds'], 59)

    def test_logout_resilience(self):
        """Audit log failure must not prevent logout."""
        self.client.login(username='logoutuser', password='pass1234')

        with patch('audit.models.AuditLog.objects.create', side_effect=Exception('DB down')):
            resp = self.client.post(reverse('logout'))

        self.assertIn(resp.status_code, [200, 302])
