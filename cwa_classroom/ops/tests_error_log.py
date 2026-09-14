"""The application log, readable in the app.

Stripe said exactly what was wrong with a student's checkout — "The price
specified is inactive" — and that sentence lived only in
/var/log/cwa/django-error.log. Finding it took an SSH session and a grep, two
weeks after the student gave up.

These cover the three things that make the page trustworthy: it shows the real
message, it never hands the filesystem to the request, and it says why it is
empty rather than implying all is well.
"""
import os
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ops.log_reader import LOG_FILES, read_log

CustomUser = get_user_model()

REAL_ERROR = (
    '[2026-09-07 23:23:35,968] ERROR accounts.views views:1082 — Stripe '
    'checkout session creation failed for user 804: The price specified is '
    'inactive. This field only accepts active prices.'
)
TRACEBACK_ENTRY = (
    '[2026-09-07 23:52:59,386] ERROR accounts.views views:430 — Stripe '
    'checkout session creation failed for institute 6 (plan 1)\n'
    'Traceback (most recent call last):\n'
    '  File "/app/accounts/views.py", line 425, in post\n'
    '    session = create_institute_checkout_session(school, plan, request)\n'
    'stripe.error.InvalidRequestError: No such price\n'
)
A_WARNING = (
    '[2026-09-08 09:00:00,000] WARNING billing.views views:12 — something mild'
)


class LogDirMixin:
    """Give each test its own log directory with real files in it."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, *lines):
        (self.log_dir / name).write_text('\n'.join(lines) + '\n')

    def settings_override(self):
        return override_settings(LOG_DIR=self.log_dir)


class ReadLogTest(LogDirMixin, TestCase):

    def test_reads_the_real_message(self):
        self.write('django-error.log', REAL_ERROR)
        with self.settings_override():
            entries, meta = read_log('error')
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['level'], 'ERROR')
        self.assertEqual(entries[0]['logger'], 'accounts.views')
        self.assertEqual(entries[0]['location'], 'views:1082')
        self.assertIn('price specified is inactive', entries[0]['message'])
        self.assertTrue(meta['available'])

    def test_newest_entry_is_first(self):
        self.write('django-error.log',
                   '[2026-09-01 10:00:00,000] ERROR a b:1 — oldest',
                   '[2026-09-02 10:00:00,000] ERROR a b:2 — newest')
        with self.settings_override():
            entries, _ = read_log('error')
        self.assertEqual(entries[0]['message'], 'newest')

    def test_traceback_stays_with_its_entry(self):
        """One line of a traceback is useless; it must not become its own row."""
        self.write('django-error.log', TRACEBACK_ENTRY)
        with self.settings_override():
            entries, _ = read_log('error')
        self.assertEqual(len(entries), 1)
        self.assertIn('institute 6', entries[0]['message'])
        self.assertIn('InvalidRequestError: No such price', entries[0]['detail'])

    def test_search_matches_message_and_logger(self):
        self.write('django-app.log', REAL_ERROR, A_WARNING)
        with self.settings_override():
            hit, _ = read_log('app', search='inactive')
            miss, _ = read_log('app', search='nothing here')
            by_logger, _ = read_log('app', search='billing.views')
        self.assertEqual(len(hit), 1)
        self.assertEqual(len(miss), 0)
        self.assertEqual(len(by_logger), 1)

    def test_level_filter(self):
        self.write('django-app.log', REAL_ERROR, A_WARNING)
        with self.settings_override():
            errors, _ = read_log('app', level='ERROR')
            warnings, _ = read_log('app', level='WARNING')
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['message'], 'something mild')

    def test_rotated_backups_are_read(self):
        """The incident was two weeks old — rotation must not hide it."""
        self.write('django-error.log', '[2026-09-08 10:00:00,000] ERROR a b:1 — recent')
        self.write('django-error.log.1', REAL_ERROR)
        with self.settings_override():
            entries, meta = read_log('error', search='inactive')
        self.assertEqual(len(entries), 1)
        self.assertIn('django-error.log.1', meta['files_read'])

    def test_limit_is_respected(self):
        self.write('django-error.log',
                   *[f'[2026-09-08 10:00:0{i},000] ERROR a b:{i} — line {i}'
                     for i in range(9)])
        with self.settings_override():
            entries, _ = read_log('error', limit=3)
        self.assertEqual(len(entries), 3)

    def test_only_the_tail_of_a_large_file_is_read(self):
        """A 10 MB log must not be loaded into memory to show 200 lines."""
        big = '\n'.join(
            f'[2026-09-08 10:00:00,000] ERROR a b:{i} — filler {i}'
            for i in range(40000))
        (self.log_dir / 'django-error.log').write_text(
            big + '\n[2026-09-08 11:00:00,000] ERROR a b:1 — the last one\n')
        self.assertGreater(os.path.getsize(self.log_dir / 'django-error.log'),
                           600 * 1024)
        with self.settings_override():
            entries, _ = read_log('error', limit=5)
        self.assertEqual(entries[0]['message'], 'the last one')

    # ── It must say WHY it is empty ──────────────────────────────────────

    def test_missing_directory_says_so(self):
        with override_settings(LOG_DIR=Path('/nonexistent/cwa-logs')):
            entries, meta = read_log('error')
        self.assertEqual(entries, [])
        self.assertFalse(meta['available'])
        self.assertIn('No log directory', meta['note'])

    def test_missing_file_is_not_reported_as_healthy(self):
        with self.settings_override():
            entries, meta = read_log('error')
        self.assertEqual(entries, [])
        self.assertFalse(meta['available'])
        self.assertIn('nothing has been written', meta['note'])

    def test_empty_result_from_a_filter_says_so(self):
        self.write('django-error.log', REAL_ERROR)
        with self.settings_override():
            entries, meta = read_log('error', search='zzz')
        self.assertEqual(entries, [])
        self.assertTrue(meta['available'])
        self.assertIn('match this filter', meta['note'])

    # ── The request never names a path ───────────────────────────────────

    def test_unknown_key_falls_back_and_never_touches_a_path(self):
        self.write('django-error.log', REAL_ERROR)
        with self.settings_override():
            for evil in ('../../etc/passwd', '/etc/passwd', 'settings.py', ''):
                _, meta = read_log(evil)
                self.assertEqual(meta['key'], 'error')
                self.assertIn(meta['file'], [f['name'] for f in LOG_FILES.values()])


class ErrorLogViewTest(LogDirMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.url = reverse('ops_error_log')
        self.client = Client()
        self.superuser = CustomUser.objects.create_superuser(
            'logadmin', 'log@test.com', 'pass1234')

    def test_superuser_sees_the_stripe_message(self):
        self.write('django-error.log', REAL_ERROR)
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'price specified is inactive')
        self.assertContains(resp, 'accounts.views')

    def test_search_filters_the_page(self):
        self.write('django-error.log', REAL_ERROR,
                   '[2026-09-08 10:00:00,000] ERROR other x:1 — unrelated thing')
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(self.url, {'q': 'inactive'})
        self.assertContains(resp, 'price specified is inactive')
        self.assertNotContains(resp, 'unrelated thing')

    def test_limit_is_capped(self):
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(self.url, {'limit': '99999'})
        self.assertEqual(resp.context['limit'], 500)

    def test_bad_limit_does_not_500(self):
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(self.url, {'limit': 'drop table'})
        self.assertEqual(resp.status_code, 200)

    def test_a_file_key_from_the_query_cannot_escape(self):
        self.write('django-error.log', REAL_ERROR)
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(self.url, {'file': '../../etc/passwd'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_file'], 'error')

    def test_empty_state_explains_itself(self):
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(self.url)
        self.assertContains(resp, 'nothing has been written')

    def test_non_superuser_is_refused(self):
        """Logs carry emails, usernames and request paths."""
        staff = CustomUser.objects.create_user('teacher', 't@test.com', 'pass1234')
        self.client.force_login(staff)
        with self.settings_override():
            resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    def test_anonymous_is_refused(self):
        with self.settings_override():
            resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    def test_reachable_from_the_ops_dashboard(self):
        self.client.force_login(self.superuser)
        with self.settings_override():
            resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertContains(resp, 'ops-log-link')
