# JSON API (`/api/v1/`)

The contract the mobile app is built against. It is **additive**: the
server-rendered htmx web app is untouched and keeps using session cookies.

## Layout

| File | What it holds |
|------|---------------|
| `authentication.py` | Bearer-token auth **plus the account-standing walls** |
| `permissions.py` | Role gates (`IsStudent`, `IsTeacher`, …) and object-level access |
| `scoping.py` | Row-level visibility — who may see whose rows |
| `exceptions.py` | The single error envelope every failure comes back in |
| `pagination.py` | Page-number pagination with a server-side cap |
| `serializers.py` | Identity (user, roles, login) |
| `urls.py` | The whole routed surface, in one registry |
| `schema.yml` | The generated OpenAPI contract (checked in — see below) |

Each app owns its own `api_views.py` / `api_serializers.py`; only the routing
is central, so a client can see the whole API in one file.

## Authentication

```
POST /api/v1/auth/login/     {"username": "...", "password": "..."} → access + refresh + user
POST /api/v1/auth/refresh/   {"refresh": "..."}                     → new access AND new refresh
POST /api/v1/auth/logout/    {"refresh": "..."}                     → 205, token revoked
GET  /api/v1/auth/me/                                               → the caller's profile
```

Send the access token as `Authorization: Bearer <token>`.

`username` also accepts an email, because the website does.

Refresh tokens **rotate**: each refresh returns a new one and blacklists the
old. The client must store what it gets back — replaying a spent token is
rejected. That is what makes logout able to actually revoke access rather than
just forgetting the token locally.

## Errors

Every failure has the same shape, so the client parses one thing:

```json
{"error": {"code": "validation_error",
           "detail": "One or more fields are invalid.",
           "fields": {"due_date": ["This field is required."]}}}
```

`code` is the stable, machine-readable part. `detail` may be reworded.

### Account standing

The web app walls a signed-in user behind an HTML page in three cases. A phone
cannot render those pages, and a 302 reads as success, so the API returns a
403 with one of these codes instead:

| `code` | Meaning |
|--------|---------|
| `account_blocked` | The account has been blocked |
| `school_suspended` | The school's account is suspended |
| `trial_expired` / `subscription_required` | Individual subscription lapsed |
| `school_subscription_expired` | The school's subscription lapsed |
| `payment_required` | A self-paying subscription is overdue |
| `profile_incomplete` | Profile or password setup unfinished |

`/api/v1/auth/` is exempt from the last one, so a newly-created student can
finish signing up from the app.

**These rules are not implemented here.** `api/authentication.py` runs the real
middlewares from `cwa_classroom/middleware.py` at the point the token becomes a
user. Why the authentication layer and not a permission class: DRF replaces
`DEFAULT_PERMISSION_CLASSES` wholesale for any view that sets
`permission_classes`, so a wall placed there stops applying to exactly the
endpoints someone thought hard about. An authentication class cannot be opted
out of that way.

## Scoping

Every list narrows through `api/scoping.py`:

* **student** → their own rows
* **parent** → rows of children linked by an active `ParentStudent`
* **teacher** → students in the classes they teach
* **institute staff** → students in schools they own or run
* **superuser** → everything

Object-level checks defer to `progress.access.can_view_student`, which the web
views already use. Not found beats forbidden: asking for a student you may not
see returns **404**, because a 403 confirms that student exists.

## What the API deliberately does not expose

* **The maths question bank.** `maths.Question` joins to `maths.Answer`, which
  carries the correct answer. Practice goes through the existing quiz views,
  which serve one question at a time and grade server-side.
* **`CodingExercise.solution_code`** — dropped per-request for non-staff.
* **`NumberPuzzle.solution`** — not in the serializer at all.
* **Homework question bodies** — `/homework/{id}/questions/` returns
  identifiers only, so the answer key is not on the device before the student
  has answered.
* **Invoice writes.** Money has one source of truth and it is the school's own
  invoicing workflow. Draft invoices are never returned either.
* **Feedback triage** — assignee, priority and Jira key stay internal.

## The schema is the contract

`api/schema.yml` is checked in and `api/tests/tests_schema.py` fails the build
when it drifts from the code. Regenerate with:

```bash
python manage.py spectacular --file api/schema.yml
```

Read the diff — it *is* the API change you are shipping. Generate the mobile
client from that file rather than hand-writing HTTP calls.

Browsable while `DEBUG=1`: `/api/docs/` (Swagger), `/api/redoc/`, `/api/schema/`.

## Settings worth knowing

| Env var | Default | Purpose |
|---------|---------|---------|
| `CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated. Empty = no cross-origin browser access |
| `API_ACCESS_TOKEN_MINUTES` | `30` | Access token lifetime |
| `API_REFRESH_TOKEN_DAYS` | `30` | Refresh token lifetime |
| `API_JWT_SIGNING_KEY` | `SECRET_KEY` | Set to rotate JWT signing independently |
| `API_THROTTLE_AUTH` | `10/min` | Login/refresh rate limit |

CORS is **not** allow-all on purpose: an allow-all API with cookie auth enabled
is a cross-site read of every logged-in user's data.

## Adding an endpoint

1. `api_serializers.py` in the owning app — list fields explicitly, never
   `__all__`; a new model column should not ship itself to the phone.
2. `api_views.py` — narrow `get_queryset()` through `api/scoping.py`.
3. Register it in `api/urls.py`.
4. Test the **negative** case: a caller who should see nothing gets nothing.
   The positive case fails loudly by hand; the negative one fails silently.
5. Regenerate `api/schema.yml`.
