"""DigitalOcean managed-database (DBaaS) metrics for the Ops dashboard.

DO does NOT expose managed-DB metrics through the /v2/monitoring REST API (that
is droplet-only). They are served as a Prometheus scrape at
``https://<host>:9273/metrics`` behind HTTP basic auth. The recurring path here
needs only those basic-auth creds (settings.DO_DB_METRICS_USER / _PASSWORD) and
the droplet added to the cluster's Trusted Sources — no API token.

Everything is best-effort: any failure (creds unset, host unreachable, cert
error, unparseable body) logs a warning and returns None, so the Ops collector
still writes its droplet snapshot and the dashboard simply omits DB tiles.

The exact metric names depend on the collector DO runs, so extraction tries the
common telegraf names first (``mem_used_percent``/``mem_available``…) then falls
back to node_exporter (``node_memory_*_bytes``). If none match we return None
rather than a wrong number.
"""
import logging
import re

logger = logging.getLogger('ops.digitalocean')

# A single Prometheus sample line: name{labels}? value [timestamp]
_SAMPLE = re.compile(
    r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'(?:\{(?P<labels>[^}]*)\})?'
    r'\s+(?P<value>[^\s]+)'
)
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def parse_prometheus(text):
    """Parse Prometheus text exposition into a list of (name, labels, value).

    Comment/HELP/TYPE lines are skipped. Values that aren't finite floats
    (``NaN``, ``+Inf``) are dropped so downstream math never sees them.
    """
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = _SAMPLE.match(line)
        if not m:
            continue
        try:
            value = float(m.group('value'))
        except ValueError:
            continue
        if value != value or value in (float('inf'), float('-inf')):  # NaN/Inf
            continue
        labels = dict(_LABEL.findall(m.group('labels') or ''))
        entries.append((m.group('name'), labels, value))
    return entries


def _values(entries, name, labels=None):
    out = []
    for n, lb, v in entries:
        if n != name:
            continue
        if labels and any(lb.get(k) != val for k, val in labels.items()):
            continue
        out.append(v)
    return out


def _first(entries, name, labels=None):
    vals = _values(entries, name, labels)
    return vals[0] if vals else None


def db_memory_pct(entries):
    """Percent RAM used (0-100), or None if no known memory metric is present."""
    used_p = _first(entries, 'mem_used_percent')
    if used_p is not None:
        return round(used_p)
    avail_p = _first(entries, 'mem_available_percent')
    if avail_p is not None:
        return round(100 - avail_p)
    total = _first(entries, 'mem_total')
    avail = _first(entries, 'mem_available')
    if total and avail is not None:
        return round((1 - avail / total) * 100)
    # node_exporter fallback (bytes).
    ntotal = _first(entries, 'node_memory_MemTotal_bytes')
    navail = _first(entries, 'node_memory_MemAvailable_bytes')
    if ntotal and navail is not None:
        return round((1 - navail / ntotal) * 100)
    return None


def db_disk_pct(entries):
    """Percent disk used (0-100) — max across mounts — or None."""
    vals = _values(entries, 'disk_used_percent')
    if vals:
        return round(max(vals))
    return None


def db_cpu_pct(entries):
    """Percent CPU busy (0-100) from telegraf's idle gauge, or None.

    Uses the cpu-total series when present so we report one whole-cluster number
    rather than a per-core reading.
    """
    idle = _first(entries, 'cpu_usage_idle', {'cpu': 'cpu-total'})
    if idle is None:
        idle = _first(entries, 'cpu_usage_idle')
    if idle is not None:
        return max(0, round(100 - idle))
    return None


def fetch_db_metrics(host, user, password, *, port=9273, timeout=10, verify=False):
    """Scrape the DBaaS Prometheus endpoint → {'mem','cpu','disk'} percents.

    Returns None (and logs a warning) on any failure or when creds are missing.
    Individual metrics inside the dict may be None if that metric wasn't found.
    """
    if not (host and user and password):
        return None

    import requests

    url = f'https://{host}:{port}/metrics'
    try:
        if not verify:
            # The :9273 endpoint presents a self-signed cert on the private
            # network; suppress the one-off insecure-request warning.
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(
            url, auth=(user, password), timeout=timeout, verify=verify,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — best-effort; never abort the cron
        logger.warning('DO DB metrics fetch failed (%s): %s', url, exc)
        return None

    entries = parse_prometheus(resp.text)
    metrics = {
        'mem': db_memory_pct(entries),
        'cpu': db_cpu_pct(entries),
        'disk': db_disk_pct(entries),
    }
    if all(v is None for v in metrics.values()):
        logger.warning(
            'DO DB metrics: scraped %d samples but no known mem/cpu/disk metric '
            'matched — check metric names at %s', len(entries), url,
        )
    return metrics
