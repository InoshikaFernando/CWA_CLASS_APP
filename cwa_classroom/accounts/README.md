# accounts

User authentication, registration, roles, and profile management for the CWA Classroom platform. Backs login/logout (with audit-logged events), password resets, multi-step profile completion, role switching, and account-blocking enforcement (unpaid fees, expired trials).

Defines the project's `AUTH_USER_MODEL` (`accounts.CustomUser`) and ships the custom auth backend that lets users sign in with either email or username.

## Key models

- **CustomUser** — extended Django user; adds date_of_birth, country, phone, address, package, terms acceptance, profile-completion flags, and account-blocking fields.
- **Role** / **UserRole** — named roles (admin, teacher, student, parent, accountant, …) plus an M2M join so a single user can hold multiple roles and switch between them.
- **PendingRegistration** — temporary record for incomplete signups awaiting email confirmation.

## URL prefix & key routes

Mounted at `/accounts/` (custom routes), then Django's built-in auth URLs are overlaid at the same prefix.

- `login/` — email-or-username login, audit-logged
- `signup/teacher/`, `register/individual-student/`, `register/school-student/` — role-specific signup flows
- `profile/`, `complete-profile/` — view/edit and onboarding
- `switch-role/` — role switcher for multi-role users

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'accounts', ...]
AUTH_USER_MODEL = 'accounts.CustomUser'
AUTHENTICATION_BACKENDS = ['accounts.backends.EmailOrUsernameBackend']
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/hub/'
LOGOUT_REDIRECT_URL = '/'

TEMPLATES[0]['OPTIONS']['context_processors'] += [
    'accounts.context_processors.user_role',
]

MIDDLEWARE += [
    'cwa_classroom.middleware.TrialExpiryMiddleware',
    'cwa_classroom.middleware.AccountBlockMiddleware',
    'cwa_classroom.middleware.ProfileCompletionMiddleware',
]
```

In root `urls.py` — order matters; custom overrides come before the Django defaults:

```python
path('accounts/', include('accounts.urls')),
path('accounts/', include('django.contrib.auth.urls')),
```

## Dependencies

- **billing** — `CustomUser.package` FK to `billing.Package`.
- **classroom** — login/auth audit events reference `classroom.School`.

## External services

SMTP only (password-reset emails via the project's email backend).
