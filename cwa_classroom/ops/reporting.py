"""Ops metrics: threshold classification + chart series for the dashboard.

The threshold logic mirrors the retired ``render_ops_dashboard.py`` (the old
GitHub Action) so alerting behaviour is unchanged now that it runs droplet-side.
"""
from collections import OrderedDict
from datetime import timedelta

from django.utils import timezone

# Selectable chart windows. `bucket` controls Python-side aggregation
# granularity (hourly for the day view, daily for the longer ones) so a
# 6-month chart stays a reasonable number of points.
WINDOWS = OrderedDict([
    ('day',   {'label': '24h',      'days': 1,   'bucket': 'hour'}),
    ('month', {'label': '30 days',  'days': 30,  'bucket': 'day'}),
    ('3m',    {'label': '3 months', 'days': 90,  'bucket': 'day'}),
    ('6m',    {'label': '6 months', 'days': 180, 'bucket': 'day'}),
])
DEFAULT_WINDOW = 'day'


def classify(metrics):
    """Classify a metrics dict into (status, crit_reasons, warn_reasons).

    Mirrors the thresholds from the old render_ops_dashboard.py:
      * RAM < 100 MB free → crit, < 200 MB → warn
      * any OOM kill in 24h → crit
      * disk ≥ 90% → crit, ≥ 80% → warn
      * a non-active/non-unknown service → crit; unknown → warn
      * load > 2× CPU count → warn
    `metrics['services']` is a {label: state} dict.
    """
    crit, warn = [], []
    mem_total = metrics.get('mem_total') or 0
    mem_avail = metrics.get('mem_avail') or 0
    oom = metrics.get('oom_24h') or 0
    disk = metrics.get('disk_used_pct') or 0
    load1 = metrics.get('load1') or 0
    nproc = metrics.get('nproc') or 1
    services = metrics.get('services') or {}

    if mem_total and mem_avail < 100:
        crit.append(f'RAM critically low ({mem_avail} MB free)')
    elif mem_total and mem_avail < 200:
        warn.append(f'RAM low ({mem_avail} MB free)')
    if oom > 0:
        crit.append(f'{oom} OOM kill(s) in last 24h')
    if disk >= 90:
        crit.append(f'Disk {disk}% full')
    elif disk >= 80:
        warn.append(f'Disk {disk}% full')

    down = [n for n, st in services.items() if st not in ('active', 'unknown')]
    if down:
        crit.append('service down: ' + ', '.join(down))
    unknown = [n for n, st in services.items() if st == 'unknown']
    if unknown:
        warn.append('service status unknown: ' + ', '.join(unknown))

    if nproc and load1 and load1 > nproc * 2:
        warn.append(f'high load ({load1} on {nproc} cpu)')

    status = 'crit' if crit else ('warn' if warn else 'ok')
    return status, crit, warn


def get_ops_series(window):
    """Bucketed chart series for the given window key.

    Aggregates OpsSnapshot rows in Python — bucketing by local hour/day and
    taking the PEAK per bucket (peaks are what matter for capacity) — to avoid
    DB-specific date truncation (MySQL Trunc* needs the tz tables loaded).

    Returns {'labels', 'mem_pct', 'swap_pct', 'disk_pct', 'rq_default',
    'rq_high', 'window'} with parallel arrays oldest→newest.
    """
    from .models import OpsSnapshot

    cfg = WINDOWS.get(window) or WINDOWS[DEFAULT_WINDOW]
    start = timezone.now() - timedelta(days=cfg['days'])
    rows = (
        OpsSnapshot.objects
        .filter(created_at__gte=start)
        .values_list(
            'created_at', 'mem_total', 'mem_used', 'swap_total', 'swap_used',
            'disk_used_pct', 'rq_default', 'rq_high',
        )
        .order_by('created_at')
    )

    fmt = '%Y-%m-%d %H:00' if cfg['bucket'] == 'hour' else '%Y-%m-%d'
    buckets = OrderedDict()
    for created, mt, mu, st, su, disk, rqd, rqh in rows:
        key = timezone.localtime(created).strftime(fmt)
        b = buckets.setdefault(
            key, {'mem': 0, 'swap': 0, 'disk': 0, 'rqd': 0, 'rqh': 0},
        )
        b['mem'] = max(b['mem'], round(mu / mt * 100) if mt else 0)
        b['swap'] = max(b['swap'], round(su / st * 100) if st else 0)
        b['disk'] = max(b['disk'], disk or 0)
        b['rqd'] = max(b['rqd'], rqd or 0)
        b['rqh'] = max(b['rqh'], rqh or 0)

    labels = list(buckets.keys())
    return {
        'labels': labels,
        'mem_pct': [buckets[k]['mem'] for k in labels],
        'swap_pct': [buckets[k]['swap'] for k in labels],
        'disk_pct': [buckets[k]['disk'] for k in labels],
        'rq_default': [buckets[k]['rqd'] for k in labels],
        'rq_high': [buckets[k]['rqh'] for k in labels],
        'window': window if window in WINDOWS else DEFAULT_WINDOW,
    }
