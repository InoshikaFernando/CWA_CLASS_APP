"""Record a droplet-health snapshot (OpsSnapshot) and alert on critical status.

Runs locally on the droplet via cron (``scripts/record_ops_metrics.sh``).
Replaces the retired ops-dashboard GitHub Action: it collects the same metrics
without SSH, stores them so the in-app Ops dashboard can draw trend charts, and
posts a Discord/Slack alert when the droplet FIRST enters a critical state
(edge-triggered off the previous snapshot, so a persistent condition doesn't
spam every run).

    python manage.py record_ops_metrics

Every collector is best-effort: on a non-Linux box, or when journalctl /
systemctl / Redis aren't reachable, it degrades to 0 / 'unknown' instead of
failing, so the snapshot is always written.
"""
import os
import shutil
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand

from ops.models import OpsSnapshot
from ops.reporting import classify


def _meminfo_mb():
    """(total, available, used) RAM in MB from /proc/meminfo; zeros if absent."""
    try:
        vals = {}
        with open('/proc/meminfo') as fh:
            for line in fh:
                key, _, rest = line.partition(':')
                vals[key.strip()] = int(rest.strip().split()[0])  # kB
        total = vals.get('MemTotal', 0) // 1024
        avail = vals.get('MemAvailable', 0) // 1024
        return total, avail, max(total - avail, 0)
    except (OSError, ValueError, IndexError):
        return 0, 0, 0


def _swap_mb():
    """(total, used) swap in MB from /proc/meminfo; zeros if absent."""
    try:
        vals = {}
        with open('/proc/meminfo') as fh:
            for line in fh:
                key, _, rest = line.partition(':')
                key = key.strip()
                if key in ('SwapTotal', 'SwapFree'):
                    vals[key] = int(rest.strip().split()[0])
        total = vals.get('SwapTotal', 0) // 1024
        free = vals.get('SwapFree', 0) // 1024
        return total, max(total - free, 0)
    except (OSError, ValueError, IndexError):
        return 0, 0


def _disk_used_pct():
    try:
        usage = shutil.disk_usage('/')
        return round(usage.used / usage.total * 100) if usage.total else 0
    except OSError:
        return 0


def _load_nproc():
    try:
        load1 = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load1 = 0.0
    return load1, (os.cpu_count() or 1)


def _oom_24h():
    try:
        out = subprocess.run(
            ['journalctl', '--since', '24 hours ago', '-k', '--no-pager'],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout
        return sum(1 for ln in out.splitlines() if 'out of memory' in ln.lower())
    except (OSError, subprocess.SubprocessError):
        return 0


def _service_state(unit):
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', unit],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def _rq_depths():
    """(default, high) prod RQ queue depths via django_rq; (None, None) if the
    queue/Redis is unavailable."""
    try:
        import django_rq
        return (
            django_rq.get_queue('default').count,
            django_rq.get_queue('high').count,
        )
    except Exception:  # noqa: BLE001 — best-effort; Redis may be down
        return None, None


class Command(BaseCommand):
    help = 'Record a droplet health snapshot and alert on critical status.'

    # Prod + shared-infra systemd units (the box also runs test, but resources
    # are whole-droplet and prod is the one we page on).
    SERVICES = {
        'gunicorn': 'cwa-gunicorn.service',
        'worker': 'cwa-rqworker-prod.service',
        'redis': 'redis-server.service',
        'caddy': 'caddy.service',
    }

    def handle(self, *args, **options):
        mem_total, mem_avail, mem_used = _meminfo_mb()
        swap_total, swap_used = _swap_mb()
        disk_pct = _disk_used_pct()
        load1, nproc = _load_nproc()
        oom = _oom_24h()
        rq_default, rq_high = _rq_depths()
        svc = {name: _service_state(unit) for name, unit in self.SERVICES.items()}

        status, crit, warn = classify({
            'mem_total': mem_total,
            'mem_avail': mem_avail,
            'oom_24h': oom,
            'disk_used_pct': disk_pct,
            'load1': load1,
            'nproc': nproc,
            'services': {
                'Gunicorn (web)': svc['gunicorn'],
                'RQ worker': svc['worker'],
                'Redis': svc['redis'],
                'Caddy': svc['caddy'],
            },
        })
        issues = '; '.join(crit + warn)[:500]

        # Edge-trigger the alert: only page when we FIRST enter crit, i.e. the
        # previous snapshot wasn't already crit. Reading it before we write the
        # new row keeps a persistent problem from alerting on every run.
        prev = OpsSnapshot.objects.order_by('-created_at').first()
        was_crit = bool(prev and prev.status == OpsSnapshot.STATUS_CRIT)

        OpsSnapshot.objects.create(
            mem_total=mem_total, mem_used=mem_used, mem_avail=mem_avail,
            swap_total=swap_total, swap_used=swap_used,
            disk_used_pct=disk_pct,
            load1=load1, nproc=nproc, oom_24h=oom,
            rq_default=rq_default, rq_high=rq_high,
            svc_gunicorn=svc['gunicorn'], svc_worker=svc['worker'],
            svc_redis=svc['redis'], svc_caddy=svc['caddy'],
            status=status, issues=issues,
        )

        if status == OpsSnapshot.STATUS_CRIT and not was_crit:
            self._alert('\U0001F534 CWA droplet ops: ' + '; '.join(crit))

        self.stdout.write(self.style.SUCCESS(
            f'ops snapshot recorded: {status}'
            + (f' — {issues}' if issues else '')
        ))

    def _alert(self, message):
        """Best-effort chat alert. Sends both Slack ('text') and Discord
        ('content') keys so either webhook works. Never raises."""
        url = getattr(settings, 'OPS_ALERT_WEBHOOK', '')
        if not url:
            self.stdout.write(
                'critical status but OPS_ALERT_WEBHOOK unset — no alert sent.')
            return
        try:
            import requests
            requests.post(
                url, json={'text': message, 'content': message}, timeout=10,
            )
        except Exception as exc:  # noqa: BLE001 — alerting must never abort
            self.stderr.write(f'ops alert POST failed: {exc}')
