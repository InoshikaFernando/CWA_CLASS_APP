"""The name the platform signs its emails with.

Production ran for months with SITE_NAME unset, so the default was what every
family actually saw: "The Classroom Team", from an address at
wizardslearninghub.co.nz, across all thirteen email templates and in the
subject line of each.

Nobody meant that. ``billing/email_utils.py`` reads
``getattr(settings, 'SITE_NAME', 'Wizards Learning Hub')`` — the real name was
written as a fallback, and ``settings`` supplying a placeholder made it
unreachable. These tests keep the placeholder from coming back, in either
place, because the failure is invisible from inside the app: nothing errors,
the emails just go out signed by the wrong company.
"""
from django.conf import settings
from django.test import TestCase

PLACEHOLDER = 'Classroom'
REAL = 'Wizards Learning Hub'


class SiteNameTests(TestCase):
    def test_the_default_is_the_real_product_name(self):
        """Read from the module rather than settings.SITE_NAME, so the test
        pins the DEFAULT and not whatever the environment happens to set."""
        import os
        import re

        with open(settings.BASE_DIR / 'cwa_classroom' / 'settings.py') as fh:
            source = fh.read()
        match = re.search(
            r"SITE_NAME = os\.environ\.get\('SITE_NAME', '([^']+)'\)", source)

        self.assertIsNotNone(match, 'SITE_NAME is no longer read from the env')
        self.assertEqual(match.group(1), REAL)

    def test_the_billing_fallback_agrees(self):
        from billing import email_utils

        self.assertNotEqual(email_utils.SITE_NAME, PLACEHOLDER)

    def test_the_classroom_fallback_agrees(self):
        """Two modules build email context and each carried its own fallback.
        They disagreed — one said Classroom, one said Wizards Learning Hub —
        which is how the wrong one went unnoticed."""
        import re

        with open(settings.BASE_DIR / 'classroom' / 'email_utils.py') as fh:
            source = fh.read()
        fallbacks = re.findall(
            r"getattr\(settings, 'SITE_NAME', '([^']+)'\)", source)

        self.assertTrue(fallbacks, 'no SITE_NAME fallback found')
        for value in fallbacks:
            self.assertEqual(value, REAL)

    def test_a_payment_notice_is_signed_with_the_real_name(self):
        """The end-to-end check: what a family actually reads."""
        from django.core import mail
        from accounts.models import CustomUser
        from billing.email_utils import notify_past_due_backlog

        student = CustomUser.objects.create_user(
            'sn_student', 'sn@example.test', 'TestPass123!',
            first_name='Ada', last_name='Lovelace')

        mail.outbox = []
        notify_past_due_backlog(student)

        body = mail.outbox[0].body
        self.assertIn(REAL, mail.outbox[0].subject)
        self.assertIn(f'The {REAL} Team', body)
        self.assertNotIn(f'The {PLACEHOLDER} Team', body)
