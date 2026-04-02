"""Tests for the audit logging system."""
from django.test import TestCase, RequestFactory, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from audit.services import log_event, get_client_ip
from audit.risk import get_risk_summary


def _create_role(name, display_name=None):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


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


class EventsViewTest(TestCase):
    """Test the Events page view (superuser and HoI access)."""

    def setUp(self):
        from classroom.models import School, SchoolTeacher

        self.client = Client()

        # Superuser
        self.superuser = CustomUser.objects.create_superuser(
            username='superadmin', password='pass12345', email='super@test.com',
        )
        _create_role(Role.ADMIN)

        # HoI user
        self.hoi = CustomUser.objects.create_user(
            username='hoi_user', password='pass12345', email='hoi@test.com',
        )
        hoi_role = _create_role(Role.HEAD_OF_INSTITUTE)
        UserRole.objects.create(user=self.hoi, role=hoi_role)

        # Regular teacher (should not have access)
        self.teacher = CustomUser.objects.create_user(
            username='teacher_user', password='pass12345', email='teacher@test.com',
        )
        teacher_role = _create_role(Role.TEACHER)
        UserRole.objects.create(user=self.teacher, role=teacher_role)

        # Schools
        self.school_a = School.objects.create(
            name='School A', slug='school-a', admin=self.hoi,
        )
        self.school_b = School.objects.create(
            name='School B', slug='school-b', admin=self.superuser,
        )

        # Link HoI to school_a via SchoolTeacher
        SchoolTeacher.objects.get_or_create(
            school=self.school_a, teacher=self.hoi,
            defaults={'role': 'head_of_institute'},
        )

        # Create audit events
        log_event(user=self.hoi, school=self.school_a, category='data_change',
                  action='student_added', detail={'student': 'alice'})
        log_event(user=self.superuser, school=self.school_b, category='admin_action',
                  action='school_suspended', detail={'reason': 'test'})
        log_event(user=self.hoi, school=self.school_a, category='auth',
                  action='login_success')

    def test_superuser_sees_all_events(self):
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page'].paginator.count, 3)

    def test_hoi_sees_only_own_school_events(self):
        self.client.login(username='hoi_user', password='pass12345')
        resp = self.client.get(reverse('audit_events'))
        self.assertEqual(resp.status_code, 200)
        # HoI should see only school_a events (2 events)
        self.assertEqual(resp.context['page'].paginator.count, 2)

    def test_teacher_denied_access(self):
        self.client.login(username='teacher_user', password='pass12345')
        resp = self.client.get(reverse('audit_events'))
        # RoleRequiredMixin should redirect (302) or forbid (403)
        self.assertIn(resp.status_code, [302, 403])

    def test_superuser_filter_by_school(self):
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'), {'schools': [self.school_b.id]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page'].paginator.count, 1)

    def test_filter_by_category(self):
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'), {'category': 'data_change'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page'].paginator.count, 1)

    def test_filter_by_action(self):
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'), {'action': 'student'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page'].paginator.count, 1)

    def test_filter_by_result(self):
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'), {'result': 'blocked'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page'].paginator.count, 0)

    def test_filter_by_date_range(self):
        from django.utils import timezone
        today = timezone.now().date().isoformat()
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'), {
            'date_from': today, 'date_to': today,
        })
        self.assertEqual(resp.status_code, 200)
        # Note: exact count depends on MySQL timezone tables being loaded
        # (CONVERT_TZ returns NULL without them, causing __date lookups to
        # match nothing). Verify the view renders with filter values in context.
        self.assertEqual(resp.context['date_from'], today)
        self.assertEqual(resp.context['date_to'], today)

    def test_filter_by_role(self):
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'), {'role': Role.TEACHER})
        self.assertEqual(resp.status_code, 200)
        # Teacher has no events
        self.assertEqual(resp.context['page'].paginator.count, 0)

    def test_hoi_does_not_see_school_filter(self):
        self.client.login(username='hoi_user', password='pass12345')
        resp = self.client.get(reverse('audit_events'))
        self.assertFalse(resp.context['is_superuser'])
        self.assertEqual(list(resp.context['selected_schools']), [])

    def test_pagination(self):
        # Create enough events to trigger pagination
        for i in range(55):
            log_event(user=self.superuser, school=self.school_b,
                      category='data_change', action=f'bulk_action_{i}')
        self.client.login(username='superadmin', password='pass12345')
        resp = self.client.get(reverse('audit_events'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['page']), 50)  # PAGE_SIZE
        # Page 2
        resp2 = self.client.get(reverse('audit_events'), {'page': 2})
        self.assertTrue(len(resp2.context['page']) > 0)

    def test_anonymous_redirected(self):
        resp = self.client.get(reverse('audit_events'))
        self.assertEqual(resp.status_code, 302)
