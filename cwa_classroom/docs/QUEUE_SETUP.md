# Background Task Queue Setup

CWA Classroom uses **django-rq** (Redis Queue) for background task processing.
This covers AI operations like PDF classification, homework grading, and content
generation.

## Architecture

- **Redis** — message broker and job store
- **django-rq** — Django integration for RQ
- **BackgroundTask model** — tracks job status, retries, and results
- **Three queues**: `high` (live grading), `default` (PDF classification),
  `low` (reports)

## Local Development

### 1. Install Redis

**Windows** (via WSL or Docker):
```bash
# WSL
sudo apt install redis-server
sudo service redis-server start

# Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

**macOS**:
```bash
brew install redis
brew services start redis
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Run migrations

```bash
python manage.py migrate taskqueue
```

### 4. Start the worker

In a separate terminal:
```bash
python manage.py rqworker high default low
```

### 5. Environment variables (optional)

```env
REDIS_URL=redis://localhost:6379/0
```

Default is `redis://localhost:6379/0` if not set.

## Production (DigitalOcean)

### Redis

```bash
sudo apt install redis-server
sudo systemctl enable redis-server
```

Redis binds to localhost by default — no external access needed.

### Environment files

Add to each env file (`/etc/cwa/cwa.env`, `/etc/cwa/cwa-test.env`,
`/etc/cwa/cwa-dev.env`):

```env
# Use different Redis DB per environment to avoid cross-contamination
REDIS_URL=redis://localhost:6379/0   # prod: db 0
REDIS_URL=redis://localhost:6379/1   # test: db 1
REDIS_URL=redis://localhost:6379/2   # dev:  db 2
```

### Worker systemd service (prod)

Create `/etc/systemd/system/cwa-rqworker.service`:

```ini
[Unit]
Description=CWA RQ Worker (prod)
After=redis-server.service cwa-gunicorn.service

[Service]
User=cwa
Group=cwa
WorkingDirectory=/home/cwa/CWA_CLASS_APP
EnvironmentFile=/etc/cwa/cwa.env
ExecStart=/home/cwa/CWA_CLASS_APP/venv/bin/python manage.py rqworker high default low
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Worker systemd service (test)

Create `/etc/systemd/system/cwa-rqworker-test.service`:

```ini
[Unit]
Description=CWA RQ Worker (test)
After=redis-server.service cwa-gunicorn-test.service

[Service]
User=cwa
Group=cwa
WorkingDirectory=/home/cwa/CWA_CLASS_APP_TEST
EnvironmentFile=/etc/cwa/cwa-test.env
ExecStart=/home/cwa/CWA_CLASS_APP_TEST/venv/bin/python manage.py rqworker high default low
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable cwa-rqworker.service
sudo systemctl start cwa-rqworker.service

# Check status
sudo systemctl status cwa-rqworker.service
journalctl -u cwa-rqworker.service -f
```

## Monitoring

- **Django Admin**: BackgroundTask model is registered — filter by status,
  task_type, school
- **RQ Dashboard**: Access via `python manage.py rqstats` or add
  `django-rq`'s URL to urlpatterns for a web dashboard
- **Stale task detection**: Tasks stuck in RUNNING for >10 minutes likely
  indicate a crashed worker — restart the worker service

## Usage

```python
from taskqueue.services import enqueue_task

task, job = enqueue_task(
    school=school,
    user=request.user,
    task_type='pdf_classify',
    func=my_task_function,
    args=[arg1, arg2],
    queue='default',
)
# task.rq_job_id — use to poll status
# task.status — pending → running → done/failed
```

## EmailQueue

The email queue (`classroom.EmailQueue`) remains on its own cron-based system
(`process_email_queue` management command, every 2 minutes). It is **not**
migrated to RQ because its daily rate limiting logic is simpler as a cron job.

**This cron is load-bearing, not a nicety.** Every invoice email is force-queued
at issue time (`invoicing_services.issue_invoices`), so the cron *is* the
delivery path: if it stops, invoices are marked issued and silently never sent.

Install it only via the `/etc/cron.d/cwa-email` drop-in written by
`deploy/setup-app-prod.sh` — never by hand with `crontab -e`. In August 2026 a
hand-added entry on the production droplet pointed at the `CWA_CLASS_APP_TEST`
checkout, so the production queue had no drainer at all and 316 invoice emails
went undelivered for ten weeks. The drop-in passes its app directory explicitly
so the path cannot drift to another checkout, and re-running the setup script
restores it.

Check it is alive:

```bash
ls -l /etc/cron.d/cwa-email
tail -20 /var/log/cwa/email_queue.log
# anything pending and older than a few minutes means the cron is not running
venv/bin/python cwa_classroom/manage.py process_email_queue --dry-run
```

A run whose oldest pending row is more than an hour old logs a WARNING saying
the queue was not drained on schedule.

**Never point a `*/2` cron at a large backlog without the wrapper.** The command
has no locking: it materialises the pending rows, then marks each sent only
after its send returns, so a second run starting mid-loop re-sends everything
the first has not reached yet. Clearing a few hundred queued emails takes longer
than the two-minute tick once the provider rate-limits, so the next tick lands
mid-drain and families get duplicate invoices. `cron_process_email_queue.sh`
runs under `flock` to prevent that — use it for manual drains too, so an
operator run and a cron tick contend for the same lock instead of racing.
