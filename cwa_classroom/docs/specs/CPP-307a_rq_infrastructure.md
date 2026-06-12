# CPP-307a: Redis + django-rq Infrastructure

## Problem

AI operations (PDF classification, homework grading, content generation) run
synchronously in request/response cycles. A 20-page PDF classification can
block the HTTP request for 15-30 seconds. The homework PDF upload already uses
`threading.Thread(daemon=True)` which silently dies if gunicorn recycles the
worker mid-task.

## Solution

Add `django-rq` (Redis Queue) as the background task framework. This is the
foundation — subsequent tickets (307b/c/d) will migrate individual workflows.

## Components

### New app: `taskqueue`

**BackgroundTask model** — thin monitoring/retry layer over RQ jobs.

| Field | Type | Purpose |
|-------|------|---------|
| school | FK → School | Tenant scoping |
| task_type | CharField(50) | e.g. `pdf_classify`, `ai_grade` |
| status | CharField(20) | pending / running / done / failed |
| rq_job_id | CharField(255) | RQ job ID, unique |
| result_data | JSONField | Task-specific result payload |
| error_message | TextField | Failure details |
| created_by | FK → User | Who triggered the task |
| created_at | DateTimeField | Auto |
| completed_at | DateTimeField | Set on done/failed |
| retry_count | SmallInt | Incremented per retry |

**Service functions:**
- `enqueue_task(school, user, task_type, func, *args, queue='default')` —
  creates BackgroundTask + enqueues RQ job
- `on_task_success(job, connection, result, *args, **kwargs)` — callback,
  marks task DONE
- `on_task_failure(job, connection, type, value, traceback)` — callback,
  marks task FAILED, stores error

### Settings

```python
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
RQ_QUEUES = {
    'high':    {'URL': REDIS_URL},
    'default': {'URL': REDIS_URL},
    'low':     {'URL': REDIS_URL},
}
```

### Queue topology

| Queue | Purpose | Examples |
|-------|---------|----------|
| high | Live user-facing operations | AI grading during homework review |
| default | Standard background tasks | PDF classification, bulk imports |
| low | Deferrable work | Report generation |

### Infrastructure (DigitalOcean)

- Redis installed via `apt install redis-server`, bound to localhost
- Separate Redis DB per environment: 0=prod, 1=test, 2=dev
- Worker runs as systemd service alongside gunicorn
- EmailQueue stays on cron (rate-limited, working well)

## What this ticket does NOT change

- No existing views modified
- No existing models modified
- EmailQueue not migrated (stays on cron)
- No UI changes (notification dropdown is CPP-307b)
