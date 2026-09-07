"""
Provision the student account the weekly browser sweep logs in as.

The sweep (``ui_tests/live/test_content_sweep.py``) walks every level and topic in a
real browser, and the quiz pages require a login. This creates that account
reproducibly instead of by hand, so it can be recreated after a test-database
refresh — which wipes it, since the test DB is restored from production.

REFUSES TO RUN ON PRODUCTION. The sweep answers quiz questions, which writes
StudentAnswer and progress rows: harmless on test, pollution on prod. The guard
is the site's own hostname, so it holds even if the command is run from the
wrong directory on the wrong box.

Idempotent: run it repeatedly to reset the password or re-apply the role.

Usage:
    python manage.py create_sweep_account --username sweepbot --password '<pw>'
    python manage.py create_sweep_account --username sweepbot   # prompts
    SWEEP_PASSWORD=... python manage.py create_sweep_account --username sweepbot

Then store the same values as the SWEEP_USERNAME / SWEEP_PASSWORD repository
secrets so .github/workflows/weekly-question-audit.yml can sign in.
"""
import getpass
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Hosts that mean "this is the live site". Sourced from the deployment runbook:
# production is www.wizardslearninghub.co.nz, test is test.*.
PRODUCTION_HOSTS = (
    'www.wizardslearninghub.co.nz',
    'wizardslearninghub.co.nz',
)


def _looks_like_production():
    """True if this Django instance is serving the production site."""
    hosts = {h.strip().lower() for h in getattr(settings, 'ALLOWED_HOSTS', [])}
    site_url = (getattr(settings, 'SITE_URL', '') or '').lower()
    for production_host in PRODUCTION_HOSTS:
        if production_host in hosts or production_host in site_url:
            # test.wizardslearninghub.co.nz contains the bare domain as a
            # suffix, so an explicit test host wins — check it did not match
            # only because of that.
            if any(h.startswith('test.') or h.startswith('staging.')
                   for h in hosts):
                continue
            return True
    return False


class Command(BaseCommand):
    help = 'Create/reset the student account used by the weekly browser sweep.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='sweepbot',
                            help='Username for the sweep account.')
        parser.add_argument('--password', default=None,
                            help='Password. Falls back to $SWEEP_PASSWORD, '
                                 'then an interactive prompt.')
        parser.add_argument('--email', default=None,
                            help='Email. Defaults to <username>@sweep.invalid.')
        parser.add_argument(
            '--allow-production', action='store_true',
            help='Override the production guard. Do not use.')

    def handle(self, *args, **options):
        from accounts.models import CustomUser, Role, UserRole

        if _looks_like_production() and not options['allow_production']:
            raise CommandError(
                'This looks like PRODUCTION (ALLOWED_HOSTS/SITE_URL name the '
                'live site). The sweep account writes quiz attempts and must '
                'only exist on test. Run it on the test droplet.'
            )

        username = options['username']
        password = (options['password']
                    or os.environ.get('SWEEP_PASSWORD')
                    or getpass.getpass(f'Password for {username}: '))
        if not password or len(password) < 12:
            raise CommandError(
                'Refusing a password under 12 characters — this account is '
                'reachable from the public test site.'
            )
        email = options['email'] or f'{username}@sweep.invalid'

        with transaction.atomic():
            user, created = CustomUser.objects.get_or_create(
                username=username,
                defaults={'email': email, 'first_name': 'Content', 'last_name': 'Sweep'},
            )
            user.set_password(password)
            user.email = user.email or email
            user.is_active = True
            # Never a superuser: it only needs to open quiz pages.
            user.is_staff = False
            user.is_superuser = False
            # Skip the onboarding gates that would otherwise redirect the
            # browser away from the quiz page.
            if hasattr(user, 'profile_completed'):
                user.profile_completed = True
            if hasattr(user, 'must_change_password'):
                user.must_change_password = False
            user.save()

            role, _ = Role.objects.get_or_create(
                name=Role.INDIVIDUAL_STUDENT,
                defaults={'display_name': 'Individual Student', 'is_active': True},
            )
            UserRole.objects.get_or_create(user=user, role=role)

        action = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f'{action} sweep account {username!r} (role: {role.name})'))
        self.stdout.write(
            'Store these as repository secrets so the weekly workflow can '
            'sign in:\n'
            f'    SWEEP_USERNAME = {username}\n'
            '    SWEEP_PASSWORD = (the password you just set)')
