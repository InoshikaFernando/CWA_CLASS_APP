"""
Unpaid-access health: the watchdog on TrialExpiryMiddleware's paywall.

A regression in that gate does not error — a delinquent account simply keeps
working and nobody is billed. These tests lock in the three surfaces that make
that visible: the health signal itself, the daily ``check_unpaid_access``
alert, and (in ops/tests.py) the Ops dashboard tile.
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser
from billing.models import Subscription
from billing.subscription_health import (
    ALLOWED_PREFIXES, DELINQUENT, MAX_LEAK_ROWS, STATUS_CRITICAL, STATUS_OK,
    STATUS_WARNING, get_unpaid_access_health, is_restricted,
)
from usage.models import PageHit

RESTRICTED = '/maths/practice/'


def _user(username, sub_status=Subscription.STATUS_PAST_DUE, active=True):
    user = CustomUser.objects.create_user(
        username=username, email=f'{username}@test.local',
        password='TestPass123!', is_active=active,
    )
    if sub_status:
        Subscription.objects.create(user=user, status=sub_status)
    return user


def _hit(user, path=RESTRICTED, ago_minutes=5, status_code=200):
    hit = PageHit.objects.create(user=user, path=path, status_code=status_code)
    # created_at is auto_now_add, so age has to be written back.
    PageHit.objects.filter(pk=hit.pk).update(
        created_at=timezone.now() - timedelta(minutes=ago_minutes))
    hit.refresh_from_db()
    return hit


class DelinquentStatusesTests(TestCase):
    def test_they_match_the_model(self):
        """DELINQUENT is spelled out, so it must be checked against the source.

        A new Subscription status that means "should be behind the wall" and is
        not listed here would make this whole check quietly under-report.
        """
        self.assertEqual(
            set(DELINQUENT),
            {Subscription.STATUS_PAST_DUE, Subscription.STATUS_EXPIRED,
             Subscription.STATUS_CANCELLED},
        )
        # And nothing that means "paid up" leaked in.
        self.assertNotIn(Subscription.STATUS_ACTIVE, DELINQUENT)
        self.assertNotIn(Subscription.STATUS_TRIALING, DELINQUENT)

    def test_allow_list_tracks_the_middleware(self):
        from cwa_classroom.middleware import TrialExpiryMiddleware
        for path in TrialExpiryMiddleware.ALLOWED_PATHS:
            self.assertIn(path, ALLOWED_PREFIXES)
            self.assertFalse(is_restricted(path))

    def test_restricted_classification(self):
        self.assertTrue(is_restricted(RESTRICTED))
        self.assertFalse(is_restricted('/billing/checkout/'))
        self.assertFalse(is_restricted('/static/css/app.css'))
        self.assertFalse(is_restricted('/accounts/login/'))


class UnpaidAccessHealthTests(TestCase):

    def test_ok_when_there_are_no_delinquent_accounts(self):
        _hit(_user('paid', sub_status=Subscription.STATUS_ACTIVE))
        health = get_unpaid_access_health()
        self.assertEqual(health['status'], STATUS_OK)
        self.assertEqual(health['delinquent'], 0)
        self.assertEqual(health['leak_count'], 0)
        self.assertEqual(health['reasons'], [])

    def test_ok_when_delinquent_accounts_only_reach_allowed_pages(self):
        user = _user('gated')
        for path in ('/billing/', '/accounts/logout/', '/static/app.js'):
            _hit(user, path=path)
        health = get_unpaid_access_health()
        self.assertEqual(health['status'], STATUS_OK)
        self.assertEqual(health['delinquent'], 1)
        self.assertEqual(health['leak_count'], 0)
        self.assertEqual(health['leaks'], [])

    def test_recent_leak_is_critical(self):
        user = _user('leaky', sub_status=Subscription.STATUS_CANCELLED)
        _hit(user, ago_minutes=10)
        _hit(user, path='/quiz/', ago_minutes=30)

        health = get_unpaid_access_health()
        self.assertEqual(health['status'], STATUS_CRITICAL)
        self.assertEqual(health['leak_count'], 1)
        self.assertEqual(health['hit_count'], 2)
        self.assertTrue(health['active_leak'])
        self.assertTrue(health['reasons'])
        leak = health['leaks'][0]
        self.assertEqual(leak['username'], 'leaky')
        self.assertEqual(leak['status'], Subscription.STATUS_CANCELLED)
        self.assertEqual(leak['count'], 2)
        self.assertEqual(leak['last_path'], RESTRICTED)

    def test_stale_leak_is_only_a_warning(self):
        """A leak that stopped days ago is history, not an open door."""
        _hit(_user('was_leaky'), ago_minutes=60 * 60)  # 2.5 days ago
        health = get_unpaid_access_health()
        self.assertEqual(health['status'], STATUS_WARNING)
        self.assertFalse(health['active_leak'])
        self.assertEqual(health['leak_count'], 1)

    def test_window_scopes_the_lookback(self):
        _hit(_user('old_leak'), ago_minutes=60 * 24 * 10)  # 10 days ago
        self.assertEqual(get_unpaid_access_health(days=7)['status'], STATUS_OK)
        self.assertEqual(
            get_unpaid_access_health(days=30)['status'], STATUS_WARNING)

    def test_non_200_responses_are_not_a_leak(self):
        """A 302 to the paywall is the gate WORKING — it must not read as a leak."""
        _hit(_user('redirected'), status_code=302)
        self.assertEqual(get_unpaid_access_health()['status'], STATUS_OK)

    def test_deactivated_accounts_are_ignored(self):
        _hit(_user('gone', active=False))
        health = get_unpaid_access_health()
        self.assertEqual(health['delinquent'], 0)
        self.assertEqual(health['status'], STATUS_OK)

    def test_username_filter_narrows_to_one_account(self):
        _hit(_user('one'))
        _hit(_user('two'))
        self.assertEqual(get_unpaid_access_health()['leak_count'], 2)
        health = get_unpaid_access_health(username='one')
        self.assertEqual(health['leak_count'], 1)
        self.assertEqual(health['leaks'][0]['username'], 'one')

    def test_leaks_are_newest_first_and_capped(self):
        for i in range(MAX_LEAK_ROWS + 3):
            _hit(_user(f'leak{i:02d}'), ago_minutes=i + 1)
        health = get_unpaid_access_health()
        self.assertEqual(health['leak_count'], MAX_LEAK_ROWS + 3)
        self.assertEqual(len(health['leaks']), MAX_LEAK_ROWS)
        self.assertTrue(health['truncated'])
        self.assertEqual(health['leaks'][0]['username'], 'leak00')

    def test_query_count_does_not_scale_with_hit_volume(self):
        """The dashboard renders this on every load, so the allow-list is applied
        in SQL: two aggregate queries plus one "last page" lookup per leaking
        account, no matter how many page views that account racked up."""
        user = _user('chatty')
        for i in range(40):
            _hit(user, path=f'/maths/q/{i}/', ago_minutes=i + 1)
        with self.assertNumQueries(3):
            get_unpaid_access_health()

        # A second leaking account adds exactly one query, not one per hit.
        second = _user('chatty2')
        for i in range(40):
            _hit(second, path=f'/quiz/q/{i}/', ago_minutes=i + 1)
        with self.assertNumQueries(4):
            get_unpaid_access_health()


class CheckUnpaidAccessCommandTests(TestCase):

    def _run(self, **kwargs):
        out, err = StringIO(), StringIO()
        try:
            call_command('check_unpaid_access', stdout=out, stderr=err, **kwargs)
            code = 0
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_exits_zero_and_reports_ok_when_clean(self):
        _user('gated')
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        self.assertIn('OK', out)
        self.assertIn('1 delinquent account(s) checked', out)

    def test_quiet_prints_nothing_when_clean(self):
        _user('gated')
        code, out, _ = self._run(quiet=True)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), '')

    def test_exits_non_zero_and_lists_the_leak(self):
        _hit(_user('leaky'))
        code, out, _ = self._run()
        self.assertEqual(code, 1)
        self.assertIn('LEAK', out)
        self.assertIn('leaky', out)
        self.assertIn(RESTRICTED, out)

    def test_quiet_still_reports_a_leak(self):
        """--quiet silences healthy runs only; an alert is never swallowed."""
        _hit(_user('leaky'))
        code, out, _ = self._run(quiet=True)
        self.assertEqual(code, 1)
        self.assertIn('LEAK', out)

    @patch('billing.management.commands.check_unpaid_access.urllib.request.urlopen')
    def test_posts_to_the_webhook_on_a_leak(self, mock_open):
        _hit(_user('leaky'))
        code, out, _ = self._run(webhook='https://hooks.example/x')
        self.assertEqual(code, 1)
        self.assertTrue(mock_open.called)
        body = mock_open.call_args[0][0].data.decode()
        self.assertIn('leaky', body)
        self.assertIn('Alert posted to webhook.', out)

    @patch('billing.management.commands.check_unpaid_access.urllib.request.urlopen')
    def test_no_webhook_call_when_clean(self, mock_open):
        _user('gated')
        self._run(webhook='https://hooks.example/x')
        self.assertFalse(mock_open.called)

    @patch('billing.management.commands.check_unpaid_access.urllib.request.urlopen',
           side_effect=OSError('boom'))
    def test_a_broken_webhook_is_surfaced_not_swallowed(self, _mock_open):
        _hit(_user('leaky'))
        code, _, err = self._run(webhook='https://hooks.example/x')
        self.assertEqual(code, 1)
        self.assertIn('Failed to post webhook alert', err)
