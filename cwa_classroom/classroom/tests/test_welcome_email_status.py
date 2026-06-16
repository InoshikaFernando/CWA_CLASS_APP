"""
Unit tests for CPP-343 welcome-email delivery status.

Covers get_welcome_email_states (latest welcome EmailLog per user, collapsed to
a display state) and that send_staff_welcome_email now writes a tracked
EmailLog (so the staff welcome email gets the same delivery tracking as other
welcome emails).
"""
import datetime
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import CustomUser
from classroom.email_service import get_welcome_email_states
from classroom.models import EmailLog, School


def _user(username, email='u@example.com'):
    return CustomUser.objects.create(username=username, email=email)


def _welcome_log(user, status, when=None, ntype='welcome'):
    log = EmailLog.objects.create(
        recipient=user, recipient_email=user.email or 'u@example.com',
        subject='Welcome', notification_type=ntype, status=status,
        provider_message_id=f'msg_{user.pk}_{status}',
    )
    if when is not None:
        EmailLog.objects.filter(pk=log.pk).update(sent_at=when)
    return log


class GetWelcomeEmailStatesTest(TestCase):

    def test_delivered_maps_to_delivered(self):
        u = _user('w_deliv')
        _welcome_log(u, 'delivered')
        self.assertEqual(get_welcome_email_states([u.id])[u.id], 'delivered')

    def test_opened_maps_to_delivered(self):
        u = _user('w_open')
        _welcome_log(u, 'opened')
        self.assertEqual(get_welcome_email_states([u.id])[u.id], 'delivered')

    def test_sent_maps_to_sent(self):
        u = _user('w_sent')
        _welcome_log(u, 'sent')
        self.assertEqual(get_welcome_email_states([u.id])[u.id], 'sent')

    def test_bounced_maps_to_bounced(self):
        u = _user('w_bounce')
        _welcome_log(u, 'bounced')
        self.assertEqual(get_welcome_email_states([u.id])[u.id], 'bounced')

    def test_failed_maps_to_failed(self):
        u = _user('w_fail')
        _welcome_log(u, 'failed')
        self.assertEqual(get_welcome_email_states([u.id])[u.id], 'failed')

    def test_no_welcome_log_absent(self):
        u = _user('w_none')
        self.assertNotIn(u.id, get_welcome_email_states([u.id]))

    def test_latest_row_wins(self):
        # A resend bounced after the original delivered → latest (bounce) wins.
        u = _user('w_latest')
        now = timezone.now()
        _welcome_log(u, 'delivered', when=now - datetime.timedelta(hours=2))
        _welcome_log(u, 'bounced', when=now, ntype='welcome_resend')
        self.assertEqual(get_welcome_email_states([u.id])[u.id], 'bounced')

    def test_non_welcome_logs_ignored(self):
        u = _user('w_other')
        _welcome_log(u, 'delivered', ntype='invoice')
        self.assertNotIn(u.id, get_welcome_email_states([u.id]))

    def test_batch_multiple_users(self):
        a, b = _user('w_a', 'a@x.com'), _user('w_b', 'b@x.com')
        _welcome_log(a, 'delivered')
        _welcome_log(b, 'failed')
        states = get_welcome_email_states([a.id, b.id])
        self.assertEqual(states[a.id], 'delivered')
        self.assertEqual(states[b.id], 'failed')


class ParentsListWelcomeStateTest(TestCase):
    """The parents admin list surfaces welcome-email delivery state for parent
    accounts (CPP-343)."""

    def setUp(self):
        from django.test import Client
        from accounts.models import Role, UserRole
        from classroom.models import SchoolStudent, ParentStudent

        self.hoi = CustomUser.objects.create_user(
            username='hoi_pl', email='hoi_pl@example.com', password='TestPass123!',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'HoI'},
        )
        UserRole.objects.create(user=self.hoi, role=role)
        self.school = School.objects.create(
            name='Parent List School', slug='parent-list-school', admin=self.hoi,
            is_active=True, is_published=True,
        )
        self.student = CustomUser.objects.create_user(
            username='stu_pl', email='stu_pl@example.com', password='TestPass123!',
        )
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)
        self.parent = CustomUser.objects.create_user(
            username='par_pl', email='par_pl@example.com', password='TestPass123!',
            first_name='Pat', last_name='Parent',
        )
        ParentStudent.objects.create(
            parent=self.parent, student=self.student, school=self.school,
            relationship='mother', is_active=True,
        )
        self.client = Client()
        self.client.force_login(self.hoi)

    def _parent_rows(self):
        from django.urls import reverse
        resp = self.client.get(
            reverse('admin_school_parents', kwargs={'school_id': self.school.id})
        )
        self.assertEqual(resp.status_code, 200)
        return {p.get('parent_id'): p for p in resp.context['page']}

    def test_delivered_welcome_state_shown(self):
        _welcome_log(self.parent, 'delivered')
        rows = self._parent_rows()
        self.assertEqual(rows[self.parent.id].get('welcome_email_state'), 'delivered')

    def test_bounced_welcome_state_shown(self):
        _welcome_log(self.parent, 'bounced')
        rows = self._parent_rows()
        self.assertEqual(rows[self.parent.id].get('welcome_email_state'), 'bounced')

    def test_no_log_leaves_state_unset(self):
        rows = self._parent_rows()
        self.assertIsNone(rows[self.parent.id].get('welcome_email_state'))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class StaffWelcomeEmailLoggingTest(TestCase):

    def test_staff_welcome_email_creates_tracked_log(self):
        from classroom.email_utils import send_staff_welcome_email

        admin = _user('staff_admin', 'admin@example.com')
        school = School.objects.create(
            name='Logging School', slug='logging-school', admin=admin,
            is_active=True,
        )
        teacher = _user('new_teacher', 'teacher@example.com')

        send_staff_welcome_email(
            teacher, plain_password='secret123', role_display='Teacher',
            school=school,
        )

        log = EmailLog.objects.filter(
            recipient=teacher, notification_type='welcome',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'sent')
        self.assertEqual(log.school_id, school.id)
