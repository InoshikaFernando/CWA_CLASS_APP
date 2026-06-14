"""
Tests for the CPP-341 payment-required notification:
  * notifications.services.send_payment_required_notification (rendering + send)
  * notify_payment_required management command (recipient selection)
"""
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import Package, Subscription
from classroom.models import School, SchoolStudent
from notifications.services import send_payment_required_notification


def _student(username, school=None, *, logged_in, profile_completed, active_sub=False,
             role=Role.STUDENT, package=None):
    user = CustomUser.objects.create_user(
        username=username, email=f'{username}@example.local', password='TestPass123!',
        profile_completed=profile_completed,
    )
    role_obj, _ = Role.objects.get_or_create(name=role, defaults={'display_name': role.title()})
    UserRole.objects.create(user=user, role=role_obj)
    if logged_in:
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
    if school is not None:
        SchoolStudent.objects.create(school=school, student=user, is_active=True)
    if active_sub:
        Subscription.objects.create(
            user=user, package=package, status=Subscription.STATUS_ACTIVE,
        )
    return user


class SendPaymentRequiredNotificationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Maths Hub Melbourne')
        self.user = _student('mhb_aryana', self.school, logged_in=True, profile_completed=False)

    def test_sends_email_with_discount_and_computed_price(self):
        ok = send_payment_required_notification(
            self.user, school=self.school,
            monthly_price='19.90', discount_code='MHMEBC75', discount_percent=75,
        )
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['mhb_aryana@example.local'])
        self.assertIn('Maths Hub Melbourne', msg.subject)
        body = msg.alternatives[0][0] if msg.alternatives else msg.body
        self.assertIn('MHMEBC75', body)
        self.assertIn('75', body)
        self.assertIn('4.98', body)          # 19.90 * 25% computed
        self.assertIn('Maths Hub Melbourne', body)

    def test_no_email_returns_false(self):
        self.user.email = ''
        self.user.save(update_fields=['email'])
        self.assertFalse(send_payment_required_notification(self.user, school=self.school))
        self.assertEqual(len(mail.outbox), 0)


class NotifyPaymentRequiredCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(name='Wizard', price=19.90, stripe_price_id='price_x')
        cls.mhb = School.objects.create(name='Maths Hub Melbourne')
        cls.other = School.objects.create(name='Other School')

        # SHOULD be emailed: re-gated + logged in + no sub + in MHB
        cls.target = _student('target', cls.mhb, logged_in=True, profile_completed=False)
        # dormant (never logged in) — skip
        cls.dormant = _student('dormant', cls.mhb, logged_in=False, profile_completed=False)
        # subscribed — skip
        cls.paid = _student('paid', cls.mhb, logged_in=True, profile_completed=False,
                            active_sub=True, package=cls.pkg)
        # other school — skip
        cls.elsewhere = _student('elsewhere', cls.other, logged_in=True, profile_completed=False)
        # individual student — skip
        cls.indiv = _student('indiv', None, logged_in=True, profile_completed=False,
                            role=Role.INDIVIDUAL_STUDENT)

    def _run(self, dry_run=False):
        out = StringIO()
        args = ['notify_payment_required', '--school', str(self.mhb.id),
                '--discount-code', 'MHMEBC75', '--discount-percent', '75']
        if dry_run:
            args.append('--dry-run')
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_emails_only_the_right_recipients(self):
        self._run()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['target@example.local'])

    def test_dry_run_sends_nothing(self):
        out = self._run(dry_run=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('target@example.local', out)
        self.assertIn('Dry run', out)

    def test_unknown_school_raises(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('notify_payment_required', '--school', '999999')
