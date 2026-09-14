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


class FeatureFlag(models.Model):
    """A feature that can be dark in one environment and live in another.

    The problem this solves is shipping unfinished work. Without it, code that
    is not ready cannot be merged, so it sits on a long-lived branch drifting
    away from ``test`` until the merge is the risky part. With it, the code
    merges immediately and stays inert until somebody turns it on.

    **The environment axis is free, and that is the point.** Test and
    production have separate databases, so a flag row on test says nothing
    about production. ``language`` can be ``pilot`` on test while production
    still reads ``off``; promoting the code does not promote the decision. No
    env var to remember, no deploy to change your mind.

    **The school axis is the ``pilot`` state.** Turn a feature on for Code
    Wizards alone, watch it for a week, then move it to ``on`` — or back to
    ``off``, which no customer ever notices because none of them could see it.

    Not to be confused with a module, which answers a different question:

    * A **module** is an entitlement — has this school *paid* for it.
    * A **flag** is a kill switch — is this code safe to run at all.

    They compose. A paid feature that is still settling carries both: the flag
    keeps it dark while it is unfinished, and the module decides who may buy it
    once it is not. A flag that is off beats a module that is bought, because
    "we are not confident in this code" outranks "they paid for it".
    """

    OFF = 'off'
    PILOT = 'pilot'
    ON = 'on'
    ROLLOUT_CHOICES = [
        (OFF, 'Off — nobody'),
        (PILOT, 'Pilot — only the schools listed below'),
        (ON, 'On — every school'),
    ]

    slug = models.SlugField(
        max_length=64, unique=True,
        help_text='The name used in code, e.g. "language".',
    )
    description = models.TextField(
        blank=True,
        help_text='What this turns on, and what to watch while it is in pilot.',
    )
    rollout = models.CharField(
        max_length=10, choices=ROLLOUT_CHOICES, default=OFF,
        help_text=(
            'Off is the default and the safe answer: a flag nobody has decided '
            'about yet is one nobody should be running.'
        ),
    )
    schools = models.ManyToManyField(
        'classroom.School', blank=True, related_name='feature_flags',
        help_text='Schools this is on for while rollout is "pilot".',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return f'{self.slug} ({self.rollout})'

    def is_enabled_for(self, school=None):
        """Whether this flag is on for ``school``.

        ``pilot`` with no school is False, not True: a background job or a
        console script has no school to match, and a piloted feature running
        unattended across every tenant is the failure the pilot exists to
        avoid.
        """
        if self.rollout == self.ON:
            return True
        if self.rollout != self.PILOT or school is None:
            return False
        return self.schools.filter(pk=getattr(school, 'pk', school)).exists()
