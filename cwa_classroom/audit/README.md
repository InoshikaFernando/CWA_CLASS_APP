# audit

Security and compliance event log. Records authentication outcomes (login attempts, lockouts, rate-limit blocks), authorization denials (entitlement / module-access checks), billing events, admin actions, and data-change events. Powers the admin audit dashboard used to investigate incidents and demonstrate compliance controls.

## Key models

- **AuditLog** — immutable event records. Fields cover: category (`auth`, `billing`, `entitlement`, `admin_action`, `data_change`), action, result (`allowed` / `blocked`), actor (user + IP + user agent), and a JSON `detail` blob for action-specific context.

## URL prefix & key routes

Mounted at the project root with admin-gated routes (e.g. `/audit/...`).

- `dashboard/` — recent-events summary
- `logs/` — searchable, filterable log list
- `events/` — event timeline view

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'audit', ...]
```

In root `urls.py`:

```python
path('', include('audit.urls')),
```

## Public service API

Other apps log events through a single helper rather than touching the model directly:

```python
from audit.services import log_event

log_event(
    category='auth',
    action='login_failed',
    result='blocked',
    user=user,                # optional
    school=school,            # optional
    request=request,          # optional — used to capture IP & UA
    detail={'reason': 'rate_limited'},
)
```

This is the integration surface the rest of the codebase consumes — call it whenever a new event is worth recording.

## Dependencies

- **accounts** — `AuditLog.user` FK to `CustomUser`.
- **classroom** — `AuditLog.school` FK to `School` for tenant scoping.

## External services

None.
