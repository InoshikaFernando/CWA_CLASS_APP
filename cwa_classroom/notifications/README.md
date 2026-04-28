# notifications

Centralised lifecycle email service. Wraps the project's email backend so that user-facing transactional emails (welcome on account creation, email-changed confirmation, password-changed confirmation) are sent consistently — with the institute CC'd, opt-out preferences honoured, and delivery logged via `classroom.EmailLog`.

This app does **not** define models — it is a services layer over the rest of the stack. It exists so that any view or service can fire a lifecycle email with a single call without duplicating boilerplate.

## Notification types

- `welcome` — sent once on account creation; institute-created vs self-registered variants
- `email_changed` — sent to the **new** address after a successful email update
- `password_changed` — sent after a successful password change (no password included)

Within each type the template is selected by role (parent / teacher / student) and by `creation_method` (institute vs self-registered) on the user.

## Key models

None — delivery is logged through `classroom.EmailLog`.

## Public service API

```python
from notifications.services import (
    send_welcome_notification,
    send_email_changed_notification,
    send_password_changed_notification,
)

# Self-registered user (no temp password):
send_welcome_notification(user)

# Institute-created user (with temporary password):
send_welcome_notification(user, plain_password='Tmp@1234', school=school)

# After email update:
send_email_changed_notification(user, new_email='new@example.com', school=school)

# After password change:
send_password_changed_notification(user, school=school)
```

All functions:

- Resolve the institute CC email automatically when `school` is omitted.
- Log success/failure via `classroom.EmailLog`.
- **Never raise** — failures are logged and swallowed so user-facing actions are never blocked by email delivery issues.

## URL prefix & key routes

The app contributes no URL routes. The public unsubscribe endpoint lives in the project urlconf and is served by `classroom.views_email.UnsubscribeView`:

```python
path('email/unsubscribe/<uuid:token>/', UnsubscribeView.as_view(), name='email_unsubscribe'),
```

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'notifications', ...]

EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'info@wizardslearninghub.co.nz')
```

When SMTP credentials are not configured, the project falls back to the console email backend automatically — `notifications` will still "send", but messages are printed instead of delivered.

No URL include is required. No middleware. No context processor.

## Dependencies

- **accounts** — `CustomUser` is the recipient and source of role / creation_method.
- **classroom** — `EmailLog` for delivery audit; `email_service.send_templated_email` for the underlying send (handles CC, preferences, logging).

## External services

- SMTP (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`) — only when credentials are set.
