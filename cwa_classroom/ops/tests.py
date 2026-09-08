"""Tests for the Ops dashboard: metric classification, chart aggregation, the
collector command (with edge-triggered alerting), and the superuser view."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ops import digitalocean as do_metrics
from ops.models import OpsSnapshot
from ops.reporting import classify, get_ops_series, WINDOWS

User = get_user_model()


class ClassifyTests(TestCase):
    def test_healthy(self):
        status, crit, warn = classify({
            'mem_total': 2000, 'mem_avail': 900, 'oom_24h': 0,
            'disk_used_pct': 40, 'load1': 0.5, 'nproc': 2,
            'services': {'Gunicorn': 'active', 'Redis': 'active'},
        })
        self.assertEqual(status, 'ok')
        self.assertEqual(crit, [])
        self.assertEqual(warn, [])

    def test_low_ram_and_oom_are_critical(self):
        status, crit, warn = classify({
            'mem_total': 2000, 'mem_avail': 80, 'oom_24h': 2,
            'disk_used_pct': 10, 'services': {},
        })
        self.assertEqual(status, 'crit')
        self.assertTrue(any('RAM critically low' in c for c in crit))
        self.assertTrue(any('OOM' in c for c in crit))

    def test_disk_warn_then_crit(self):
        _, _, warn = classify({'disk_used_pct': 85, 'services': {}})
        self.assertTrue(any('Disk 85% full' in w for w in warn))
        status, crit, _ = classify({'disk_used_pct': 95, 'services': {}})
        self.assertEqual(status, 'crit')
        self.assertTrue(any('Disk 95% full' in c for c in crit))

    def test_service_down_is_critical_but_unknown_is_only_warn(self):
        status, crit, _ = classify({'services': {'Gunicorn': 'failed'}})
        self.assertEqual(status, 'crit')
        self.assertTrue(any('service down' in c for c in crit))

        status, _, warn = classify({'services': {'Caddy': 'unknown'}})
        self.assertEqual(status, 'warn')
        self.assertTrue(any('unknown' in w for w in warn))


class SeriesTests(TestCase):
    def test_buckets_peak_per_day_and_is_window_scoped(self):
        now = timezone.now()
        # Two snapshots today (peak RAM should win), one 100 days ago.
        OpsSnapshot.objects.create(mem_total=1000, mem_used=400, disk_used_pct=30)
        OpsSnapshot.objects.create(mem_total=1000, mem_used=700, disk_used_pct=50)
        old = OpsSnapshot.objects.create(mem_total=1000, mem_used=900, disk_used_pct=88)
        OpsSnapshot.objects.filter(pk=old.pk).update(
            created_at=now - timedelta(days=100))

        month = get_ops_series('month')
        # 30-day window excludes the 100-day-old row; today's bucket peaks at 70%.
        self.assertEqual(month['mem_pct'][-1], 70)
        self.assertEqual(month['disk_pct'][-1], 50)

        three = get_ops_series('3m')
        # 90 days still excludes the 100-day row.
        self.assertNotIn(88, three['disk_pct'])

    def test_rq_zero_kept_but_none_stays_null(self):
        # A real empty queue (0) must stay 0; an unknown reading (Redis down,
        # NULL) must stay null so the chart shows a gap, not a healthy 0.
        OpsSnapshot.objects.create(
            mem_total=1000, mem_used=100, rq_default=0, rq_high=None)
        s = get_ops_series('day')
        self.assertEqual(s['rq_default'][-1], 0)
        self.assertIsNone(s['rq_high'][-1])

    def test_empty_series_is_safe(self):
        s = get_ops_series('day')
        self.assertEqual(s['labels'], [])
        self.assertEqual(s['mem_pct'], [])

    def test_unknown_window_falls_back(self):
        s = get_ops_series('bogus')
        self.assertEqual(s['window'], 'day')

    def test_db_mem_series_peaks_and_keeps_null_gap(self):
        # A captured DB reading is charted (peak per bucket); an unconfigured /
        # failed scrape (None) stays a gap, never a healthy 0.
        OpsSnapshot.objects.create(mem_total=1000, mem_used=500, db_mem_pct=85)
        OpsSnapshot.objects.create(mem_total=1000, mem_used=500, db_mem_pct=91)
        s = get_ops_series('day')
        self.assertEqual(s['db_mem_pct'][-1], 91)

        OpsSnapshot.objects.all().delete()
        OpsSnapshot.objects.create(mem_total=1000, mem_used=500, db_mem_pct=None)
        s = get_ops_series('day')
        self.assertIsNone(s['db_mem_pct'][-1])


class DigitalOceanMetricsTests(TestCase):
    """Prometheus parsing + best-effort scrape of the managed-DB metrics."""

    # Mirrors the real db-mysql-syd1-cwa exposition (labels + telegraf names).
    TELEGRAF = (
        '# HELP mem_available_percent available memory\n'
        '# TYPE mem_available_percent gauge\n'
        'mem_used_percent{host="db-1"} 60.0\n'       # excludes cache — must LOSE
        'mem_available_percent{host="db-1"} 10.0\n'  # DO's basis — must WIN
        'disk_used_percent{path="/var/lib/mysql"} 8.9\n'
        'cpu_usage_idle{cpu="cpu-total"} 92.34\n'
        'cpu_usage_idle{cpu="cpu0"} 92.34\n'
    )

    def test_parse_and_extract(self):
        e = do_metrics.parse_prometheus(self.TELEGRAF)
        # Available-based (100 - 10) matches DO's alert, NOT mem_used_percent 60.
        self.assertEqual(do_metrics.db_memory_pct(e), 90)
        self.assertEqual(do_metrics.db_disk_pct(e), 9)       # round(8.9)
        self.assertEqual(do_metrics.db_cpu_pct(e), 8)        # 100 - 92.34 -> 8

    def test_memory_from_available_bytes(self):
        e = do_metrics.parse_prometheus('mem_total 1000\nmem_available 250\n')
        self.assertEqual(do_metrics.db_memory_pct(e), 75)

    def test_memory_available_percent_variant(self):
        e = do_metrics.parse_prometheus('mem_available_percent 30\n')
        self.assertEqual(do_metrics.db_memory_pct(e), 70)

    def test_memory_falls_back_to_used_percent(self):
        # Only telegraf "used" present (no available metric) → use it as-is.
        e = do_metrics.parse_prometheus('mem_used_percent 55\n')
        self.assertEqual(do_metrics.db_memory_pct(e), 55)

    def test_memory_node_exporter_fallback(self):
        e = do_metrics.parse_prometheus(
            'node_memory_MemTotal_bytes 1000\nnode_memory_MemAvailable_bytes 100\n')
        self.assertEqual(do_metrics.db_memory_pct(e), 90)

    def test_unknown_metrics_return_none(self):
        e = do_metrics.parse_prometheus('# just a comment\nsomething_else 5\n')
        self.assertIsNone(do_metrics.db_memory_pct(e))
        self.assertIsNone(do_metrics.db_disk_pct(e))
        self.assertIsNone(do_metrics.db_cpu_pct(e))

    def test_nan_and_inf_are_dropped(self):
        e = do_metrics.parse_prometheus('mem_used_percent NaN\nmem_total +Inf\n')
        self.assertIsNone(do_metrics.db_memory_pct(e))

    def test_fetch_returns_none_without_creds(self):
        self.assertIsNone(do_metrics.fetch_db_metrics('', '', ''))
        self.assertIsNone(do_metrics.fetch_db_metrics('host', '', 'pw'))

    @patch('requests.get')
    def test_fetch_scrapes_and_parses(self, mock_get):
        resp = MagicMock()
        resp.text = 'mem_used_percent 91\ndisk_used_percent{path="/"} 40\n'
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        out = do_metrics.fetch_db_metrics('h', 'u', 'p')
        self.assertEqual(out['mem'], 91)
        self.assertEqual(out['disk'], 40)
        # Basic auth + the :9273 metrics URL were used.
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs['auth'], ('u', 'p'))
        self.assertIn(':9273/metrics', mock_get.call_args[0][0])

    @patch('requests.get', side_effect=RuntimeError('unreachable'))
    def test_fetch_failure_returns_none(self, _mock_get):
        self.assertIsNone(do_metrics.fetch_db_metrics('h', 'u', 'p'))


class RecordCommandTests(TestCase):
    """The collector is patched so it never touches the real OS/Redis."""

    PATCH = 'ops.management.commands.record_ops_metrics'

    def _run_with(self, *, mem_avail=900, disk=40, oom=0, gunicorn='active'):
        with patch(f'{self.PATCH}._meminfo_mb', return_value=(2000, mem_avail, 2000 - mem_avail)), \
             patch(f'{self.PATCH}._swap_mb', return_value=(1000, 100)), \
             patch(f'{self.PATCH}._disk_used_pct', return_value=disk), \
             patch(f'{self.PATCH}._load_nproc', return_value=(0.4, 2)), \
             patch(f'{self.PATCH}._oom_24h', return_value=oom), \
             patch(f'{self.PATCH}._rq_depths', return_value=(3, 0)), \
             patch(f'{self.PATCH}._service_state', return_value=gunicorn):
            call_command('record_ops_metrics')

    def test_records_healthy_snapshot(self):
        self._run_with()
        snap = OpsSnapshot.objects.get()
        self.assertEqual(snap.status, 'ok')
        self.assertEqual(snap.mem_used, 1100)
        self.assertEqual(snap.rq_default, 3)
        self.assertEqual(snap.svc_gunicorn, 'active')

    @patch(f'{PATCH}.Command._alert')
    def test_alerts_once_on_entering_crit(self, mock_alert):
        # First crit run → alerts.
        self._run_with(mem_avail=50)
        self.assertEqual(OpsSnapshot.objects.latest('created_at').status, 'crit')
        self.assertEqual(mock_alert.call_count, 1)

        # Still crit → no repeat alert (edge-triggered).
        self._run_with(mem_avail=50)
        self.assertEqual(mock_alert.call_count, 1)

        # Recovers, then crits again → alerts again.
        self._run_with(mem_avail=900)
        self._run_with(mem_avail=50)
        self.assertEqual(mock_alert.call_count, 2)

    def test_alert_noop_without_webhook(self):
        # _alert runs for real here; with no webhook configured it must not raise.
        with self.settings(OPS_ALERT_WEBHOOK=''):
            self._run_with(mem_avail=50)
        self.assertEqual(OpsSnapshot.objects.count(), 1)

    def test_db_metrics_null_when_unconfigured(self):
        # No DO_DB_METRICS_* creds → no scrape, DB fields stay null.
        self._run_with()
        snap = OpsSnapshot.objects.get()
        self.assertIsNone(snap.db_mem_pct)
        self.assertFalse(snap.db_metrics_available)

    def test_db_metrics_stored_when_configured(self):
        with self.settings(DO_DB_METRICS_USER='u', DO_DB_METRICS_PASSWORD='p',
                           DO_DB_METRICS_HOST='dbhost'):
            with patch(f'{self.PATCH}.fetch_db_metrics',
                       return_value={'mem': 88, 'cpu': 10, 'disk': 40}) as m:
                self._run_with()
        snap = OpsSnapshot.objects.latest('created_at')
        self.assertEqual(snap.db_mem_pct, 88)
        self.assertEqual(snap.db_cpu_pct, 10)
        self.assertEqual(snap.db_disk_pct, 40)
        self.assertTrue(snap.db_metrics_available)
        m.assert_called_once()


class PruneCommandTests(TestCase):
    def test_prunes_old_rows_only(self):
        fresh = OpsSnapshot.objects.create(mem_total=1000, mem_used=500)
        stale = OpsSnapshot.objects.create(mem_total=1000, mem_used=500)
        OpsSnapshot.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=500))
        call_command('prune_ops_metrics', '--days', '400')
        self.assertTrue(OpsSnapshot.objects.filter(pk=fresh.pk).exists())
        self.assertFalse(OpsSnapshot.objects.filter(pk=stale.pk).exists())


class OpsDashboardViewTests(TestCase):
    def setUp(self):
        self.super = User.objects.create_superuser(
            username='boss', email='boss@example.local', password='Pass123!')
        User.objects.create_user(
            username='plain', email='plain@example.local', password='Pass123!')

    def test_requires_superuser(self):
        self.client.login(username='plain', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_renders_with_snapshot_and_window(self):
        OpsSnapshot.objects.create(
            mem_total=2000, mem_used=1500, mem_avail=500, disk_used_pct=42,
            rq_default=5, rq_high=0, svc_gunicorn='active', status='ok')
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'), {'window': '3m'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Droplet Health')
        self.assertEqual(resp.context['window'], '3m')
        self.assertEqual(resp.context['bucket_label'], 'day')  # long windows bucket by day
        self.assertEqual(resp.context['latest'].disk_used_pct, 42)

    def test_day_window_labels_buckets_as_hour(self):
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))  # default = day
        self.assertEqual(resp.context['bucket_label'], 'hour')

    def test_renders_empty_state(self):
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['latest'])
        self.assertFalse(resp.context['latest_stale'])

    def test_fresh_snapshot_is_not_stale(self):
        OpsSnapshot.objects.create(
            mem_total=2000, mem_used=1000, mem_avail=1000, status='ok')
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertFalse(resp.context['latest_stale'])
        self.assertNotContains(resp, 'Stale data')

    def test_old_snapshot_is_flagged_stale(self):
        # A snapshot older than the threshold means the recorder cron has
        # stalled; the dashboard must warn rather than present it as current.
        snap = OpsSnapshot.objects.create(
            mem_total=2000, mem_used=1000, mem_avail=1000, status='ok')
        OpsSnapshot.objects.filter(pk=snap.pk).update(
            created_at=timezone.now() - timedelta(hours=6))
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertTrue(resp.context['latest_stale'])
        self.assertContains(resp, 'Stale data')

    def test_db_tiles_shown_when_metrics_present(self):
        OpsSnapshot.objects.create(
            mem_total=2000, mem_used=1000, mem_avail=1000,
            db_mem_pct=91, db_cpu_pct=12, db_disk_pct=40, status='ok')
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertContains(resp, 'Managed database')
        self.assertContains(resp, '91%')  # DB memory tile

    def test_db_tiles_hidden_without_metrics(self):
        OpsSnapshot.objects.create(
            mem_total=2000, mem_used=1000, mem_avail=1000, status='ok')
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertNotContains(resp, 'Managed database')

    def test_stale_banner_hides_status_banner(self):
        # A stale critical reading isn't the current state, so the crit banner
        # is suppressed in favour of the stale warning.
        snap = OpsSnapshot.objects.create(
            mem_total=2000, mem_used=1990, mem_avail=10, status='crit',
            issues='RAM critically low (10 MB free)')
        OpsSnapshot.objects.filter(pk=snap.pk).update(
            created_at=timezone.now() - timedelta(hours=6))
        self.client.login(username='boss', password='Pass123!')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertContains(resp, 'Stale data')
        # The status banner renders "Critical: <issues>" as one run of text;
        # the incidents table splits status and details across cells, so this
        # contiguous string is unique to the (now-suppressed) banner.
        self.assertNotContains(resp, 'Critical: RAM critically low (10 MB free)')


class OpsDashboardUnpaidAccessTests(TestCase):
    """The paywall watchdog's tile.

    The daily check_unpaid_access cron alerts to Discord; this section is the
    same signal where a superuser will actually see it. A leak that shows only
    in a chat channel nobody re-reads is a leak nobody acts on.
    """

    def setUp(self):
        self.super = User.objects.create_superuser(
            username='boss', email='boss@example.local', password='Pass123!')
        self.client.login(username='boss', password='Pass123!')

    @staticmethod
    def _delinquent(username, status=None):
        from billing.models import Subscription
        user = User.objects.create_user(
            username=username, email=f'{username}@example.local',
            password='Pass123!')
        Subscription.objects.create(
            user=user, status=status or Subscription.STATUS_PAST_DUE)
        return user

    @staticmethod
    def _hit(user, path='/maths/practice/', ago_minutes=5):
        from usage.models import PageHit
        hit = PageHit.objects.create(user=user, path=path, status_code=200)
        PageHit.objects.filter(pk=hit.pk).update(
            created_at=timezone.now() - timedelta(minutes=ago_minutes))

    def test_healthy_paywall_renders_without_a_banner(self):
        self._delinquent('gated')
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Subscription access')
        self.assertEqual(resp.context['unpaid_access']['status'], 'ok')
        self.assertContains(resp, 'Holding')
        self.assertNotContains(resp, 'Unpaid accounts are getting in')
        self.assertContains(resp, 'the paywall is doing its job')

    def test_active_leak_shows_the_banner_and_the_offending_account(self):
        self._hit(self._delinquent('leaky'))
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.context['unpaid_access']['status'], 'critical')
        self.assertContains(resp, 'Unpaid accounts are getting in')
        self.assertContains(resp, 'leaky')
        self.assertContains(resp, '/maths/practice/')

    def test_stale_leak_is_shown_as_a_warning_not_an_emergency(self):
        self._hit(self._delinquent('was_leaky'), ago_minutes=60 * 60)
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.context['unpaid_access']['status'], 'warning')
        self.assertContains(resp, 'Unpaid access seen recently')
        self.assertNotContains(resp, 'Unpaid accounts are getting in')

    def test_section_renders_with_no_subscriptions_at_all(self):
        resp = self.client.get(reverse('ops_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No delinquent subscriptions to check')


class PaymentDelayTileTests(TestCase):
    """The ops page carries the "locked out and not told" count.

    The unpaid-access tiles next to it watch the paywall letting people in.
    This one watches it locking people out silently, which is the half that
    went unnoticed for weeks: nothing errors, the family just stops coming
    back.
    """

    def setUp(self):
        self.super = User.objects.create_superuser(
            username='pdboss', email='pdboss@example.local', password='Pass123!')
        self.client.login(username='pdboss', password='Pass123!')

    def _past_due(self, username, email):
        from billing.models import Package, Subscription
        package, _ = Package.objects.get_or_create(
            name='Ops Monthly',
            defaults={'price': 19.90, 'stripe_price_id': 'price_ops'})
        user = User.objects.create_user(username, email, 'Pass123!')
        Subscription.objects.create(
            user=user, package=package, status=Subscription.STATUS_PAST_DUE)
        return user

    def test_the_tile_is_present_and_quiet_with_nothing_outstanding(self):
        resp = self.client.get(reverse('ops_admin_dashboard'))

        self.assertContains(resp, 'Payment delays')
        self.assertEqual(resp.context['payment_delays']['status'], 'ok')
        self.assertContains(resp, 'no failed payments')

    def test_an_untold_family_shows_on_the_tile(self):
        self._past_due('pd_ops', 'pd_ops@example.local')

        resp = self.client.get(reverse('ops_admin_dashboard'))

        health = resp.context['payment_delays']
        self.assertEqual((health['count'], health['untold']), (1, 1))
        self.assertContains(resp, '1 not told')
        # The page has to say what to do about it, or the number is trivia.
        self.assertContains(resp, 'notify_past_due --send')
