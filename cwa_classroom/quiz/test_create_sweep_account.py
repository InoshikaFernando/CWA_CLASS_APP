"""Tests for ``manage.py create_sweep_account``.

The production guard carries the weight here: the sweep account answers quiz
questions, so creating it on the live site would write attempt and progress
rows against real students' data.
"""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import CustomUser, Role, UserRole

TEST_HOSTS = ['test.wizardslearninghub.co.nz']
PROD_HOSTS = ['www.wizardslearninghub.co.nz']
PASSWORD = 'sweep-pass-long-enough'


@override_settings(ALLOWED_HOSTS=TEST_HOSTS,
                   SITE_URL='https://test.wizardslearninghub.co.nz')
class CreateSweepAccountTests(TestCase):

    def test_creates_a_student_account(self):
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', PASSWORD)
        user = CustomUser.objects.get(username='sweepbot')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.is_active)
        self.assertTrue(
            UserRole.objects.filter(
                user=user, role__name=Role.INDIVIDUAL_STUDENT).exists())

    def test_account_is_never_privileged(self):
        # It only needs to open quiz pages.
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', PASSWORD)
        user = CustomUser.objects.get(username='sweepbot')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_onboarding_gates_are_cleared(self):
        # Otherwise the browser is redirected to complete-profile and never
        # reaches a quiz.
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', PASSWORD)
        user = CustomUser.objects.get(username='sweepbot')
        if hasattr(user, 'profile_completed'):
            self.assertTrue(user.profile_completed)
        if hasattr(user, 'must_change_password'):
            self.assertFalse(user.must_change_password)

    def test_is_idempotent_and_resets_the_password(self):
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', PASSWORD)
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', 'a-different-password')
        self.assertEqual(CustomUser.objects.filter(username='sweepbot').count(), 1)
        user = CustomUser.objects.get(username='sweepbot')
        self.assertTrue(user.check_password('a-different-password'))

    def test_short_password_is_refused(self):
        with self.assertRaises(CommandError):
            call_command('create_sweep_account',
                         '--username', 'sweepbot', '--password', 'short')
        self.assertFalse(CustomUser.objects.filter(username='sweepbot').exists())


class ProductionGuardTests(TestCase):

    @override_settings(ALLOWED_HOSTS=PROD_HOSTS,
                       SITE_URL='https://www.wizardslearninghub.co.nz')
    def test_refuses_to_run_on_production(self):
        with self.assertRaises(CommandError) as ctx:
            call_command('create_sweep_account',
                         '--username', 'sweepbot', '--password', PASSWORD)
        self.assertIn('PRODUCTION', str(ctx.exception))
        self.assertFalse(CustomUser.objects.filter(username='sweepbot').exists())

    @override_settings(ALLOWED_HOSTS=TEST_HOSTS,
                       SITE_URL='https://test.wizardslearninghub.co.nz')
    def test_test_host_is_allowed(self):
        # 'test.wizardslearninghub.co.nz' contains the production domain as a
        # suffix — the guard must not trip on that.
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', PASSWORD)
        self.assertTrue(CustomUser.objects.filter(username='sweepbot').exists())

    @override_settings(ALLOWED_HOSTS=['localhost', '127.0.0.1'],
                       SITE_URL='http://localhost:8000')
    def test_local_development_is_allowed(self):
        call_command('create_sweep_account',
                     '--username', 'sweepbot', '--password', PASSWORD)
        self.assertTrue(CustomUser.objects.filter(username='sweepbot').exists())

    @override_settings(ALLOWED_HOSTS=PROD_HOSTS,
                       SITE_URL='https://www.wizardslearninghub.co.nz')
    def test_explicit_override_is_honoured(self):
        # An escape hatch must exist, but only when asked for by name.
        call_command('create_sweep_account', '--username', 'sweepbot',
                     '--password', PASSWORD, '--allow-production')
        self.assertTrue(CustomUser.objects.filter(username='sweepbot').exists())
