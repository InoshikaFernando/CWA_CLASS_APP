"""Who ``notify_payment_required`` actually emails, under each audience.

The command sends real email to real families, so the interesting assertions
are all about who is NOT on the list. Two failures matter more than the rest:

* **Missing the people you meant to reach.** The original audience requires
  ``profile_completed=False`` and a previous login. A student coming off a free
  promotion fails both — their profile IS complete and they HAVE logged in — so
  the promotion's own audience was invisible to the command written for it.
* **Reaching people you did not.** Anyone currently paying must never receive
  an email asking them to start paying, and nobody may be emailed twice.

``--dry-run`` is used throughout where the recipient list is what is being
checked, so the tests assert on the list the command prints rather than on
mocked sends. That is the same list the operator reads before pressing go.
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, UserRole
from billing.models import Package, Subscription
from classroom.models import ParentStudent, School, SchoolStudent

User = get_user_model()


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return role


class NotifyAudiences(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Wizard', price=19.90, stripe_price_id='price_blast_test')
        admin = User.objects.create_user(
            username='blast_admin', email='blast_admin@test.local',
            password='TestPass123!')
        cls.school = School.objects.create(
            name='Blast School', slug='blast-school', admin=admin)

    def _student(self, username, *, status=None, profile_completed=True,
                 logged_in=True, enrol=True):
        user = User.objects.create_user(
            username=username, email=f'{username}@test.local',
            password='TestPass123!', profile_completed=profile_completed)
        UserRole.objects.create(user=user, role=_role(Role.STUDENT))
        if logged_in:
            User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        if enrol:
            SchoolStudent.objects.create(
                school=self.school, student=user, is_active=True)
        if status is not None:
            Subscription.objects.create(
                user=user, package=self.package, status=status)
        return user

    def _parent_of(self, student, username):
        parent = User.objects.create_user(
            username=username, email=f'{username}@test.local',
            password='TestPass123!')
        UserRole.objects.create(user=parent, role=_role(Role.PARENT))
        ParentStudent.objects.create(
            parent=parent, student=student, school=self.school, is_active=True)
        return parent

    def _run(self, *args):
        out = StringIO()
        call_command('notify_payment_required', '--school', str(self.school.id),
                     *args, stdout=out, stderr=out)
        return out.getvalue()

    # -- the gap this was built to close ------------------------------------

    def test_the_default_audience_cannot_see_a_lapsed_promotion_student(self):
        """Their profile is complete and they have logged in — both disqualify.

        Not a bug in the original audience; it was written for a different job.
        It is the reason a second one exists.
        """
        self._student('mhm_lapsed', status=Subscription.STATUS_EXPIRED,
                      profile_completed=True, logged_in=True)

        self.assertIn('No re-gated, logged-in students',
                      self._run('--dry-run'))

    def test_the_unsubscribed_audience_reaches_them(self):
        self._student('mhm_lapsed', status=Subscription.STATUS_EXPIRED,
                      profile_completed=True, logged_in=True)

        output = self._run('--audience', 'unsubscribed', '--dry-run')
        self.assertIn('mhm_lapsed@test.local', output)

    def test_it_reaches_a_student_who_never_subscribed_or_logged_in(self):
        """The recruitment half of the list."""
        self._student('never_started', status=None, logged_in=False)

        output = self._run('--audience', 'unsubscribed', '--dry-run')
        self.assertIn('never_started@test.local', output)

    # -- and never the wrong people -----------------------------------------

    def test_a_paying_student_is_never_emailed(self):
        self._student('paying', status=Subscription.STATUS_ACTIVE)
        self._student('on_trial', status=Subscription.STATUS_TRIALING)

        output = self._run('--audience', 'unsubscribed', '--dry-run')
        self.assertIn('No unsubscribed students', output)

    def test_another_school_is_out_of_scope(self):
        other = School.objects.create(
            name='Other', slug='other-blast',
            admin=User.objects.create_user(
                username='other_blast_admin',
                email='other_blast_admin@test.local', password='TestPass123!'))
        theirs = self._student('theirs', enrol=False)
        SchoolStudent.objects.create(school=other, student=theirs,
                                     is_active=True)
        self._student('ours')

        output = self._run('--audience', 'unsubscribed', '--dry-run')
        self.assertIn('ours@test.local', output)
        self.assertNotIn('theirs@test.local', output)

    def test_an_individual_student_is_out_of_scope(self):
        """They buy their own plan; this email is about a school account."""
        user = self._student('individual')
        UserRole.objects.create(
            user=user, role=_role(Role.INDIVIDUAL_STUDENT))

        self.assertIn('No unsubscribed students',
                      self._run('--audience', 'unsubscribed', '--dry-run'))

    # -- parents -------------------------------------------------------------

    def test_parents_are_only_included_when_asked_for(self):
        student = self._student('kid')
        self._parent_of(student, 'kids_mum')

        without = self._run('--audience', 'unsubscribed', '--dry-run')
        self.assertNotIn('kids_mum@test.local', without)

        with_parents = self._run('--audience', 'unsubscribed',
                                 '--include-parents', '--dry-run')
        self.assertIn('kids_mum@test.local', with_parents)
        self.assertIn('kid@test.local', with_parents)

    def test_a_parent_of_two_unsubscribed_children_is_emailed_once(self):
        first = self._student('twin_a')
        second = self._student('twin_b')
        parent = self._parent_of(first, 'twins_dad')
        ParentStudent.objects.create(
            parent=parent, student=second, school=self.school, is_active=True)

        output = self._run('--audience', 'unsubscribed', '--include-parents',
                           '--dry-run')
        self.assertEqual(output.count('twins_dad@test.local'), 1)

    def test_a_parent_of_a_paying_child_is_not_emailed(self):
        paying = self._student('paid_kid', status=Subscription.STATUS_ACTIVE)
        self._parent_of(paying, 'paid_kids_mum')

        self.assertIn('No unsubscribed students',
                      self._run('--audience', 'unsubscribed',
                                '--include-parents', '--dry-run'))

    @patch('notifications.services.send_payment_required_notification')
    def test_a_parent_is_emailed_on_behalf_of_their_child_s_school(
            self, _unused):
        """A parent belongs to no school of their own, so the school has to be
        carried across or the email goes out with its name missing."""
        from notifications.management.commands import notify_payment_required

        student = self._student('school_kid')
        parent = self._parent_of(student, 'school_kids_mum')

        pairs = notify_payment_required.Command._parents_of(
            [student], default_school=None)

        self.assertEqual(len(pairs), 1)
        emailed_parent, school = pairs[0]
        self.assertEqual(emailed_parent, parent)
        self.assertEqual(school, self.school)

    # -- the link and the code ----------------------------------------------

    @patch('notifications.management.commands.notify_payment_required.time.sleep')
    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_the_campaign_link_replaces_the_login_button(
            self, mock_send, _sleep):
        self._student('linked')

        self._run('--audience', 'unsubscribed',
                  '--discount-code', 'MHM2WEEKS', '--discount-percent', '100',
                  '--link-url', 'https://example.test/start/')

        self.assertTrue(mock_send.called)
        context = mock_send.call_args.kwargs['context']
        self.assertEqual(context['login_url'], 'https://example.test/start/')
        self.assertEqual(context['discount_code'], 'MHM2WEEKS')

    @patch('notifications.management.commands.notify_payment_required.time.sleep')
    @patch('classroom.email_service.send_templated_email', return_value=True)
    def test_without_a_link_the_button_still_points_somewhere(
            self, mock_send, _sleep):
        """An empty --link-url must not blank the href."""
        self._student('unlinked')

        self._run('--audience', 'unsubscribed')

        context = mock_send.call_args.kwargs['context']
        self.assertTrue(context['login_url'])
        self.assertIn('/accounts/login/', context['login_url'])

    # -- sending twice -------------------------------------------------------

    def test_a_re_run_does_not_email_the_same_family_again(self):
        """Driven off the EmailLog row a real send leaves behind.

        Written against the log rather than by sending twice with a mocked
        mailer, because a mocked mailer writes no log — the idempotency guard
        would look like it worked while actually never having anything to skip.
        """
        from classroom.models import EmailLog
        from notifications.services import NOTIF_PAYMENT_REQUIRED

        student = self._student('once_only')
        self.assertIn('once_only@test.local',
                      self._run('--audience', 'unsubscribed', '--dry-run'))

        EmailLog.objects.create(
            recipient=student, recipient_email=student.email,
            subject='Action needed', notification_type=NOTIF_PAYMENT_REQUIRED,
            status='sent')

        output = self._run('--audience', 'unsubscribed', '--dry-run')
        self.assertIn('already emailed', output)
        self.assertNotIn('once_only@test.local', output)

    def test_resend_reaches_them_again_when_that_is_what_you_want(self):
        from classroom.models import EmailLog
        from notifications.services import NOTIF_PAYMENT_REQUIRED

        student = self._student('nudge_again')
        EmailLog.objects.create(
            recipient=student, recipient_email=student.email,
            subject='Action needed', notification_type=NOTIF_PAYMENT_REQUIRED,
            status='sent')

        output = self._run('--audience', 'unsubscribed', '--resend',
                           '--dry-run')
        self.assertIn('nudge_again@test.local', output)

    def test_the_dry_run_writes_nothing_and_says_so(self):
        self._student('rehearsed')

        output = self._run('--audience', 'unsubscribed', '--dry-run')

        self.assertIn('Dry run', output)
        from classroom.models import EmailLog
        self.assertFalse(EmailLog.objects.exists())


class TheOriginalAudienceStillWorks(TestCase):
    """The re-gating nudge is unchanged: same predicate, same people.

    It emails real guardians, and the new audience was added beside it rather
    than on top of it precisely so this could be asserted.
    """

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Wizard', price=19.90, stripe_price_id='price_regate_test')
        admin = User.objects.create_user(
            username='regate_admin', email='regate_admin@test.local',
            password='TestPass123!')
        cls.school = School.objects.create(
            name='Regate School', slug='regate-school', admin=admin)

    def _student(self, username, *, profile_completed, logged_in, status=None):
        user = User.objects.create_user(
            username=username, email=f'{username}@test.local',
            password='TestPass123!', profile_completed=profile_completed)
        UserRole.objects.create(user=user, role=_role(Role.STUDENT))
        if logged_in:
            User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        SchoolStudent.objects.create(
            school=self.school, student=user, is_active=True)
        if status is not None:
            Subscription.objects.create(
                user=user, package=self.package, status=status)
        return user

    def _run(self, *args):
        out = StringIO()
        call_command('notify_payment_required', '--school', str(self.school.id),
                     *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_it_emails_a_regated_student_who_has_logged_in(self):
        self._student('regated', profile_completed=False, logged_in=True)
        self.assertIn('regated@test.local', self._run('--dry-run'))

    def test_it_still_skips_a_dormant_account(self):
        """They meet the payment gate naturally on first login."""
        self._student('dormant', profile_completed=False, logged_in=False)
        self.assertIn('No re-gated, logged-in students', self._run('--dry-run'))

    def test_it_still_skips_a_student_who_is_not_regated(self):
        self._student('fine', profile_completed=True, logged_in=True)
        self.assertIn('No re-gated, logged-in students', self._run('--dry-run'))

    def test_it_still_skips_a_paying_student(self):
        self._student('regated_but_paying', profile_completed=False,
                      logged_in=True, status=Subscription.STATUS_ACTIVE)
        self.assertIn('No re-gated, logged-in students', self._run('--dry-run'))
