"""Tests for the Ops dashboard: metric classification, chart aggregation, the
collector command (with edge-triggered alerting), and the superuser view."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
