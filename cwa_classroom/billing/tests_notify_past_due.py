"""The one-off that clears the backlog of un-notified failed payments.

41 `invoice.payment_failed` events were processed against a subscription id the
handler could not read, so nobody was ever written to. The reader is fixed, but
that only helps the next failure — Stripe does not resend a spent event, and
its retry schedule for these subscriptions may be exhausted. Without this the
backlog is never told at all.

The load-bearing property is that it does NOT send by default. Emailing real
families is not undoable, and a command that mails on a bare invocation is one
tab-complete away from doing it by accident.
"""
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from accounts.models import CustomUser
from audit.models import AuditLog
from billing.models import Package, Subscription
from classroom.models import ParentStudent


def run(**kwargs):
    out = StringIO()
    call_command('notify_past_due', stdout=out, stderr=out, **kwargs)
    return out.getvalue()


class NotifyPastDueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='NPD Monthly', price=19.90, stripe_price_id='price_npd')

    def setUp(self):
        mail.outbox = []

    def _student(self, name, status=Subscription.STATUS_PAST_DUE,
                 email='child@example.test', parent_email='payer@example.test'):
        user = CustomUser.objects.create_user(name, email, 'TestPass123!')
        if parent_email:
            parent = CustomUser.objects.create_user(
                f'{name}_p', parent_email, 'TestPass123!')
            ParentStudent.objects.create(
                parent=parent, student=user, is_active=True)
        Subscription.objects.create(
            user=user, package=self.package, status=status)
        return user

    # -- the safety property ------------------------------------------------
    def test_the_default_sends_nothing(self):
        self._student('npd_a')

        out = run()

        self.assertEqual(mail.outbox, [])
        self.assertIn('DRY RUN', out)
        self.assertIn('would', out)

    def test_a_dry_run_leaves_no_notified_marker(self):
        """Otherwise a dry run would silence the real send that follows it."""
        self._student('npd_dry')

        run()

        self.assertFalse(AuditLog.objects.filter(
            action='payment_failed_notice_sent').exists())

    # -- sending ------------------------------------------------------------
    def test_send_writes_to_the_student_and_the_parent(self):
        self._student('npd_b')

        run(send=True)

        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(mail.outbox[0].to,
                              ['child@example.test', 'payer@example.test'])

    def test_only_past_due_is_notified(self):
        """A cancelled subscription is not "your card failed, please update it"
        — telling someone who deliberately left to fix their payment is worse
        than saying nothing."""
        self._student('npd_cancelled', status=Subscription.STATUS_CANCELLED,
                      email='gone@example.test', parent_email='goneparent@example.test')
        self._student('npd_due')

        run(send=True)

        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('gone@example.test', mail.outbox[0].to)

    def test_an_active_subscription_is_never_notified(self):
        self._student('npd_active', status=Subscription.STATUS_ACTIVE)

        run(send=True)

        self.assertEqual(mail.outbox, [])

    # -- idempotency --------------------------------------------------------
    def test_running_twice_does_not_write_twice(self):
        self._student('npd_c')

        run(send=True)
        mail.outbox = []
        out = run(send=True)

        self.assertEqual(mail.outbox, [])
        self.assertIn('already notified', out)

    def test_force_overrides_the_marker(self):
        self._student('npd_d')
        run(send=True)
        mail.outbox = []

        run(send=True, force=True)

        self.assertEqual(len(mail.outbox), 1)

    def test_a_later_lapse_is_notified_again(self):
        """Already told means told since THIS lapse, not ever. A student who
        failed, paid, and failed again is owed a second notice."""
        user = self._student('npd_e')
        run(send=True)
        mail.outbox = []

        sub = Subscription.objects.get(user=user)
        sub.save()          # auto_now moves updated_at: a fresh lapse

        run(send=True)

        self.assertEqual(len(mail.outbox), 1)

    # -- unreachable --------------------------------------------------------
    def test_a_student_nobody_can_be_reached_for_is_named_not_skipped(self):
        CustomUser.objects.create_user('npd_nobody', None, 'TestPass123!')
        Subscription.objects.create(
            user=CustomUser.objects.get(username='npd_nobody'),
            package=self.package, status=Subscription.STATUS_PAST_DUE)

        out = run(send=True)

        self.assertIn('NOBODY', out)
        self.assertIn('no address', out)
        self.assertEqual(mail.outbox, [])

    def test_a_student_with_no_parent_is_still_written_to(self):
        self._student('npd_alone', parent_email=None)

        run(send=True)

        self.assertEqual(mail.outbox[0].to, ['child@example.test'])

    def test_the_send_is_audit_logged_with_its_recipients(self):
        user = self._student('npd_f')

        run(send=True)

        ev = AuditLog.objects.filter(
            user=user, action='payment_failed_notice_sent').first()
        self.assertIsNotNone(ev)
        self.assertCountEqual(ev.detail['recipients'],
                              ['child@example.test', 'payer@example.test'])


class PastDuePanelTests(TestCase):
    """The dashboard says whether anyone has actually been told.

    "6 past due" is the number you can do least with. A family that has been
    emailed is waiting on a card; one that has not is waiting on us — and for
    41 failed payments nobody was told at all while the donut showed a tidy
    count. That difference is what this panel exists to surface.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Role, UserRole
        cls.package = Package.objects.create(
            name='Panel Monthly', price=19.90, stripe_price_id='price_panel')
        cls.su = CustomUser.objects.create_superuser(
            'panel_su', 'su@example.test', 'TestPass123!')

    def setUp(self):
        self.client.force_login(self.su)

    def _past_due(self, name, email='p@example.test', parent_email=None):
        user = CustomUser.objects.create_user(name, email, 'TestPass123!')
        if parent_email:
            parent = CustomUser.objects.create_user(
                f'{name}_p', parent_email, 'TestPass123!')
            ParentStudent.objects.create(
                parent=parent, student=user, is_active=True)
        Subscription.objects.create(
            user=user, package=self.package,
            status=Subscription.STATUS_PAST_DUE)
        return user

    def _panel(self):
        from billing.views_admin import SubscriptionOverviewView
        return SubscriptionOverviewView._past_due_rows()

    def test_an_untold_student_is_counted_as_untold(self):
        self._past_due('panel_a')

        panel = self._panel()

        self.assertEqual(panel['count'], 1)
        self.assertEqual(panel['untold'], 1)
        self.assertFalse(panel['rows'][0]['notified'])

    def test_a_notified_student_is_no_longer_untold(self):
        user = self._past_due('panel_b')
        run(send=True)

        panel = self._panel()

        self.assertEqual(panel['untold'], 0)
        self.assertTrue(panel['rows'][0]['notified'])

    def test_a_notice_from_before_this_lapse_does_not_count(self):
        """Told means told about THIS failure. An older notice shown as current
        hides a family nobody has contacted."""
        user = self._past_due('panel_c')
        run(send=True)
        sub = Subscription.objects.get(user=user)
        sub.save()          # a fresh lapse, after the notice

        self.assertEqual(self._panel()['untold'], 1)

    def test_a_student_nobody_can_be_reached_for_is_flagged_separately(self):
        """Not the same problem as "not told yet" — no amount of sending fixes
        it, so it must not sit in the queue of things to send."""
        user = CustomUser.objects.create_user('panel_d', None, 'TestPass123!')
        Subscription.objects.create(
            user=user, package=self.package,
            status=Subscription.STATUS_PAST_DUE)

        panel = self._panel()

        self.assertEqual(panel['unreachable'], 1)
        self.assertEqual(panel['untold'], 0)
        self.assertFalse(panel['rows'][0]['reachable'])

    def test_the_parents_address_is_listed_for_the_row(self):
        self._past_due('panel_e', parent_email='mum@example.test')

        self.assertIn('mum@example.test', self._panel()['rows'][0]['emails'])

    def test_only_past_due_appears(self):
        user = CustomUser.objects.create_user(
            'panel_ok', 'ok@example.test', 'TestPass123!')
        Subscription.objects.create(
            user=user, package=self.package, status=Subscription.STATUS_ACTIVE)

        self.assertEqual(self._panel()['count'], 0)

    def test_the_panel_renders_on_the_dashboard(self):
        from django.urls import reverse
        self._past_due('panel_f')

        response = self.client.get(
            reverse('billing_admin_subscription_overview'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'past-due-panel')
        self.assertContains(response, 'not told')

    def test_the_panel_is_absent_when_nothing_has_failed(self):
        """An empty "Payment failed" heading reads as a section that is broken
        rather than a state worth celebrating."""
        from django.urls import reverse

        response = self.client.get(
            reverse('billing_admin_subscription_overview'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'past-due-panel')
