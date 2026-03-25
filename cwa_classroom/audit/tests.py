"""Tests for the audit logging system."""
from django.test import TestCase, RequestFactory

from accounts.models import CustomUser
from audit.models import AuditLog
from audit.services import log_event, get_client_ip
from audit.risk import get_risk_summary


class AuditLogModelTest(TestCase):
    """Test AuditLog model."""

    def test_create_log(self):
        log = AuditLog.objects.create(
            category='auth',
            action='login_success',
            result='allowed',
            detail={'username': 'testuser'},
            ip_address='192.168.1.1',
        )
        self.assertEqual(log.action, 'login_success')
        self.assertEqual(log.result, 'allowed')
        self.assertIn('username', log.detail)

    def test_ordering_newest_first(self):
        AuditLog.objects.create(category='auth', action='first')
        AuditLog.objects.create(category='auth', action='second')
        logs = list(AuditLog.objects.values_list('action', flat=True))
        # Ordering is -created_at, -pk; when timestamps match, higher pk comes first
        self.assertEqual(logs[0], 'second')


class LogEventServiceTest(TestCase):
    """Test log_event() helper function."""

    def test_basic_log_event(self):
        log_event(category='auth', action='test_action')
        self.assertEqual(AuditLog.objects.count(), 1)
        log = AuditLog.objects.first()
        self.assertEqual(log.action, 'test_action')

    def test_log_event_with_user(self):
        user = CustomUser.objects.create_user(username='loguser', password='pass')
        log_event(user=user, category='auth', action='user_test')
        log = AuditLog.objects.first()
        self.assertEqual(log.user, user)

    def test_log_event_with_request(self):
        factory = RequestFactory()
        request = factory.get('/test/', HTTP_USER_AGENT='TestBot/1.0')
        log_event(category='auth', action='request_test', request=request)
        log = AuditLog.objects.first()
        self.assertEqual(log.ip_address, '127.0.0.1')
        self.assertIn('TestBot', log.user_agent)
        self.assertEqual(log.endpoint, '/test/')

    def test_log_event_with_detail(self):
        log_event(
            category='entitlement', action='module_denied',
            result='blocked', detail={'module': 'attendance'},
        )
        log = AuditLog.objects.first()
        self.assertEqual(log.detail['module'], 'attendance')
        self.assertEqual(log.result, 'blocked')

    def test_log_event_never_crashes(self):
        """log_event should never raise exceptions."""
        # Pass invalid data — should fail silently
        log_event(category='x' * 100, action='y' * 200)
        # Should not crash even with nonsense

    def test_log_event_with_unsaved_user(self):
        """Unsaved users should not crash log_event."""
        user = CustomUser(username='unsaved')
        log_event(user=user, category='auth', action='unsaved_test')
        # Should not crash


class GetClientIPTest(TestCase):
    """Test IP extraction."""

    def test_direct_ip(self):
        factory = RequestFactory()
        request = factory.get('/')
        self.assertEqual(get_client_ip(request), '127.0.0.1')

    def test_forwarded_ip(self):
        factory = RequestFactory()
        request = factory.get('/', HTTP_X_FORWARDED_FOR='203.0.113.50, 70.41.3.18')
        self.assertEqual(get_client_ip(request), '203.0.113.50')

    def test_none_request(self):
        self.assertIsNone(get_client_ip(None))


class RiskSummaryTest(TestCase):
    """Test risk summary function."""

    def test_empty_summary(self):
        summary = get_risk_summary()
        self.assertEqual(summary['login_failures_24h'], 0)
        self.assertEqual(summary['payment_failures_7d'], 0)
        self.assertEqual(summary['module_denials_7d'], 0)

    def test_summary_counts_correctly(self):
        log_event(category='auth', action='login_failed', result='blocked')
        log_event(category='auth', action='login_failed', result='blocked')
        log_event(category='billing', action='payment_failed', result='blocked')
        summary = get_risk_summary()
        self.assertEqual(summary['login_failures_24h'], 2)
        self.assertEqual(summary['payment_failures_7d'], 1)
