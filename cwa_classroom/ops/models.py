from django.db import models


class OpsSnapshot(models.Model):
    """A point-in-time snapshot of droplet health.

    Recorded by the ``record_ops_metrics`` management command (droplet-side
    cron). Resources (RAM/swap/disk/load) are whole-droplet — prod, test and
    dev share one box; RQ depth and service status are the prod environment's.

    Powers the superuser Ops dashboard's trend charts and incident timeline.
    Rows are pruned after ~13 months by ``prune_ops_metrics`` so the 6-month
    window always has data with margin.
    """
    STATUS_OK = 'ok'
    STATUS_WARN = 'warn'
    STATUS_CRIT = 'crit'
    STATUS_CHOICES = [
        (STATUS_OK, 'OK'),
        (STATUS_WARN, 'Watch'),
        (STATUS_CRIT, 'Critical'),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Memory / swap (MB).
    mem_total = models.PositiveIntegerField(default=0)
    mem_used = models.PositiveIntegerField(default=0)
    mem_avail = models.PositiveIntegerField(default=0)
    swap_total = models.PositiveIntegerField(default=0)
    swap_used = models.PositiveIntegerField(default=0)

    # Disk (root fs), percent used.
    disk_used_pct = models.PositiveSmallIntegerField(default=0)

    # Load average (1m) and CPU count.
    load1 = models.FloatField(default=0)
    nproc = models.PositiveSmallIntegerField(default=1)

    # OOM kills seen in the last 24h.
    oom_24h = models.PositiveIntegerField(default=0)

    # Prod RQ queue depth (null when Redis was unreachable at capture).
    rq_default = models.IntegerField(null=True, blank=True)
    rq_high = models.IntegerField(null=True, blank=True)

    # Managed DB (DigitalOcean DBaaS) utilisation %, scraped from the cluster's
    # Prometheus endpoint. Null when DB metrics aren't configured or the scrape
    # failed — distinct from a real 0 — so the dashboard can omit DB tiles
    # rather than plot a misleading zero.
    db_mem_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    db_cpu_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    db_disk_pct = models.PositiveSmallIntegerField(null=True, blank=True)

    # systemd service state: active / inactive / failed / unknown.
    svc_gunicorn = models.CharField(max_length=12, default='unknown')
    svc_worker = models.CharField(max_length=12, default='unknown')
    svc_redis = models.CharField(max_length=12, default='unknown')
    svc_caddy = models.CharField(max_length=12, default='unknown')

    # Overall status derived at capture time + the "; "-joined reasons.
    status = models.CharField(
        max_length=4, choices=STATUS_CHOICES, default=STATUS_OK, db_index=True,
    )
    issues = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['created_at'])]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} — {self.status}'

    @property
    def mem_used_pct(self):
        return round(self.mem_used / self.mem_total * 100) if self.mem_total else 0

    @property
    def swap_used_pct(self):
        return round(self.swap_used / self.swap_total * 100) if self.swap_total else 0

    @property
    def db_metrics_available(self):
        """True when at least one managed-DB metric was captured."""
        return any(
            v is not None
            for v in (self.db_mem_pct, self.db_cpu_pct, self.db_disk_pct)
        )

    @property
    def services(self):
        """Label -> state, for the dashboard's service tiles."""
        return {
            'Gunicorn (web)': self.svc_gunicorn,
            'RQ worker': self.svc_worker,
            'Redis': self.svc_redis,
            'Caddy': self.svc_caddy,
        }
