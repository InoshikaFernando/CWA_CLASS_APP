# CPP-XXX: WhatsApp Parent Notifications

## Overview

Parents currently learn about homework only by logging into the app or via
email. This feature pushes two time-sensitive events to parents over WhatsApp:
(1) when a teacher **publishes homework**, every parent of an active student in
that class gets a message; (2) when a student **submits homework**, that
student's parent(s) get the result. WhatsApp is the highest-open-rate channel
our parent base actually checks. The feature ships **inert** — no message can
leave the system until Meta credentials, approved templates, and per-parent
opt-in exist — mirroring the Resend delivery-tracking and Discord rollouts.

Provider is **Meta WhatsApp Cloud API (direct)**, chosen for cost at our volume
(~6k utility messages/month). It sits behind a `WhatsAppProvider` abstraction so
Twilio or an unofficial group-posting backend can be swapped in later without
touching call sites.

## User stories

- **As a teacher**, when I publish homework to my class, I want every parent of
  my active students to receive a WhatsApp message, so that homework gets done
  without me chasing.
- **As a parent**, I want a WhatsApp message when homework is set and another
  when my child submits with their score, so that I can support my child
  without logging in.
- **As a parent**, I want to opt in/out of WhatsApp notifications and confirm
  the number on file, so that I control how the school contacts me.
- **As a HoI**, I want to enable WhatsApp for my school, see delivery status,
  and know which parents are unreachable (no number / not opted in), so that I
  can trust the channel and chase gaps.
- **As a HoD**, I want department-scoped visibility of WhatsApp delivery for the
  classes in my department, so that I can spot delivery problems.
- **As a student**: *no direct interaction* — students neither receive nor
  configure WhatsApp messages. Intentionally excluded.

## Data model

New standalone app: **`whatsapp`**. Tenant data scopes by `School`. Soft-delete
via `removed_at` where records are user-managed (preferences); append-only logs
do not soft-delete.

### `WhatsAppConfig` — per-school enablement (null-inheritance to global default)

| Field | Type | Purpose |
|-------|------|---------|
| school | FK → School, null=True, unique | Tenant. `NULL` row = global default. |
| is_enabled | BooleanField, null=True | `NULL` inherits global default. Tri-state. |
| notify_on_publish | BooleanField, null=True | Toggle event 1, inherits if NULL. |
| notify_on_submission | BooleanField, null=True | Toggle event 2, inherits if NULL. |
| sender_phone_id | CharField(64), blank | Meta phone-number ID override (else env). |
| removed_at | DateTimeField, null=True | Soft delete. |
| created_at / updated_at | DateTimeField | Auto. |

> Resolution: a school value of `NULL` inherits the global (`school=NULL`) row;
> the global default itself defaults to **disabled** so the feature is inert
> until a HoI/admin explicitly turns it on.

### `WhatsAppPreference` — per-parent opt-in

| Field | Type | Purpose |
|-------|------|---------|
| user | FK → CustomUser, unique | The parent. |
| phone | CharField(30), blank | Confirmed E.164 number; falls back to resolution chain if blank. |
| opted_in | BooleanField, default=False | **Must be True to send.** Explicit opt-in (WhatsApp requirement). |
| opted_in_at | DateTimeField, null=True | Consent timestamp (audit). |
| opted_out_at | DateTimeField, null=True | Set when parent sends STOP / toggles off. |
| receive_publish | BooleanField, default=True | Per-parent mute of event 1. |
| receive_results | BooleanField, default=True | Per-parent mute of event 2. |
| unsubscribe_token | UUIDField | One-click/opt-out link, mirrors EmailPreference. |

### `WhatsAppTemplate` — registry of Meta-approved templates

| Field | Type | Purpose |
|-------|------|---------|
| key | CharField(50), unique | Internal key, e.g. `homework_published`, `homework_result`. |
| meta_template_name | CharField(100) | Name as approved in Meta. |
| language_code | CharField(10), default `en` | Template locale. |
| category | CharField(20) | `utility` (enforced). |
| is_active | BooleanField | Gate sends if template unapproved/paused. |
| body_param_order | JSONField | Documents positional `{{1}}…` → field mapping. |

### `WhatsAppMessageLog` — append-only delivery log (mirrors `EmailLog`)

| Field | Type | Purpose |
|-------|------|---------|
| school | FK → School, indexed, null=True | Tenant scoping. |
| recipient | FK → CustomUser, null=True | Parent (null if number-only). |
| recipient_phone | CharField(30) | E.164 number messaged. |
| template | FK → WhatsAppTemplate, null=True | Which template. |
| event_type | CharField(30) | `homework_published` / `homework_result`. |
| related_homework | FK → homework.Homework, null=True | Context. |
| related_submission | FK → homework.HomeworkSubmission, null=True | Context (event 2). |
| status | CharField(20) | `queued / sent / delivered / read / failed / undeliverable`. |
| provider_message_id | CharField(255), indexed | Meta `wamid`, for webhook correlation. |
| error_code / error_detail | CharField / TextField | Meta failure payload. |
| sent_at / delivered_at / read_at / failed_at | DateTimeField, null | Status timestamps. |
| created_at | DateTimeField, auto_now_add | Enqueue time. |

> Status precedence: reuse the `EmailLog.STATUS_RANK` / `apply_delivery_event()`
> pattern so a late `sent` webhook never overwrites a terminal `failed`/`read`.

### Changed model: `classroom.ClassRoom`

| Field | Type | Purpose |
|-------|------|---------|
| whatsapp_group_id | CharField(64), blank | Stored now for the future "group later" backend. Unused by the official Cloud API path. |

> Stored on `ClassRoom` to avoid a second migration later. No behaviour attached
> in this epic — purely a forward-compat column.

## Resolution / inheritance rules

### Should this school send at all? (tri-state null-inheritance)

```
school.WhatsAppConfig.is_enabled  (True/False)
  → if NULL → global WhatsAppConfig.is_enabled (school=NULL)
    → if NULL → False  (hard default: inert)
```

Same chain for `notify_on_publish` / `notify_on_submission`.

### Which parents receive a message for a student? (recipient resolution)

```
1. ParentStudent.objects.filter(student=student, is_active=True)
     → each .parent (CustomUser)
2. For each parent, the phone number:
     WhatsAppPreference.phone (if set)
       → CustomUser.phone
         → StudentGuardian → Guardian.phone   (fallback contact)
           → (no number) → log as `undeliverable`, skip send
3. Gate each parent on ALL of:
     - WhatsAppConfig resolves enabled for the school
     - WhatsAppPreference.opted_in == True
     - the per-event toggle (receive_publish / receive_results) == True
     - a non-blank, valid E.164 number was resolved
     - WhatsAppTemplate for the event is_active
4. Dedupe by normalized phone number  (one parent with several children in the
   class, or two children submitting, must not be messaged twice for the same
   event+context).
```

> Multi-child parents: dedupe by `(phone, event_type, related_object_id)`.
> Multi-parent students: each opted-in parent is messaged (then deduped by
> phone so shared numbers collapse).

## Views, URLs, templates

App `whatsapp`, URL prefix `/whatsapp/`.

| View | URL | Method | Type | Purpose |
|------|-----|--------|------|---------|
| `WhatsAppWebhookView` | `/whatsapp/webhook/` | GET/POST | API | GET = Meta verification challenge; POST = delivery-status callbacks → `apply_delivery_event()`. |
| `ParentWhatsAppPrefsView` | `/whatsapp/preferences/` | GET/POST | HTMX partial | Parent opt-in toggle, number confirm, per-event mutes. |
| `WhatsAppUnsubscribeView` | `/whatsapp/unsubscribe/<token>/` | GET/POST | Page | Tokenised opt-out (no login), mirrors email unsubscribe. |
| `SchoolWhatsAppSettingsView` | `/whatsapp/settings/` | GET/POST | HTMX partial | HoI enable/disable + event toggles for their school. |
| `WhatsAppDeliveryLogView` | `/whatsapp/logs/` | GET | HTMX partial | HoI/HoD delivery dashboard, school/department scoped. |

**No new homework views.** The two events hook into existing views via the
service layer (see Migration & rollout).

**Service layer** (`whatsapp/services.py`):
- `notify_homework_published(homework)` — resolves recipients across the class,
  enqueues one send per deduped parent.
- `notify_submission_result(submission)` — resolves the submitting student's
  parents, enqueues result send.
- `send_template(parent, template_key, params, context)` — gate checks +
  `WhatsAppMessageLog(status=queued)` + `enqueue_task(...)`.
- `_resolve_parent_phone(parent, student)` — the fallback chain above.

**Provider layer** (`whatsapp/providers/`):
- `base.py` — `WhatsAppProvider.send_template(to, template, params) -> wamid`.
- `meta_cloud.py` — primary backend (Graph API).
- `twilio.py`, `unofficial_group.py` — stubs raising `NotImplementedError`,
  selected by `WHATSAPP_PROVIDER` env var.

**RQ task** (`whatsapp/tasks.py`):
- `deliver_whatsapp_message(log_id)` — runs in worker, calls provider, updates
  the log with `provider_message_id` / `status`.

## Permissions

Default deny. Role → view access:

| View | HoI | HoD | Teacher | Parent | Student |
|------|-----|-----|---------|--------|---------|
| SchoolWhatsAppSettings | ✅ own school | ❌ | ❌ | ❌ | ❌ |
| WhatsAppDeliveryLog | ✅ school-wide | ✅ dept classes | ❌ | ❌ | ❌ |
| ParentWhatsAppPrefs | ❌ | ❌ | ❌ | ✅ self | ❌ |
| WhatsAppUnsubscribe | token-auth (no login) |||| |
| WhatsAppWebhook | Meta signature-verified (no app auth) |||| |

Teachers **trigger** sends by publishing homework but cannot configure or view
delivery (kept lightweight; can be added later if requested).

## Edge cases

- **Feature off / inert:** if WhatsAppConfig resolves disabled, services no-op
  silently (no log rows). This is the default state on ship.
- **Tenant isolation:** recipient resolution and logs always filter by the
  homework's `school`; a parent with children in two schools is messaged per
  school context only.
- **Soft-deleted records:** skip students/parents where `is_active=False` or
  `removed_at` set; skip inactive `ClassStudent`.
- **Multi-child parent:** dedupe by phone per event+context (no duplicate
  "homework published" for the same class).
- **Missing parent / no ParentStudent row:** no recipient → log
  `undeliverable` against the student for the HoI dashboard, no crash.
- **Missing/invalid phone:** fallback chain to Guardian.phone; if still blank or
  non-E.164 → `undeliverable`, skip.
- **Not opted in:** never sent; surfaced in the delivery dashboard as a gap.
- **Template not approved / paused:** `is_active=False` blocks the event;
  service logs `failed` with reason, never calls Meta.
- **Messaging tier / rate limit:** Meta caps business-initiated messages
  (1k/24h for a new number, auto-scaling). RQ queue + per-school throttle
  spreads bursts; 429s retry with backoff via existing task retry.
- **Provider/Meta outage:** sends are async — homework publish and submission
  succeed regardless; failed tasks retry (max 3) then mark `failed`.
- **max_attempts > 1:** result message sent on **final/best submission only**
  (configurable), not every attempt — avoids spamming and inflating cost.
- **Role transitions:** a user who loses the Parent role stops resolving as a
  recipient (gated on active `ParentStudent`).
- **STOP / opt-out:** inbound `STOP` via webhook sets `opted_out_at`,
  `opted_in=False`; future sends skip.

## Migration & rollout

1. **Migration A — new app:** create `whatsapp` tables. No data backfill.
2. **Migration B — `ClassRoom.whatsapp_group_id`:** additive nullable column
   (low risk; note prod schema-drift precedent — verify the column lands).
3. **Seed:** global `WhatsAppConfig(school=NULL, is_enabled=False)` +
   `WhatsAppTemplate` rows (`is_active=False` until Meta approves them) via
   data migration / fixture.
4. **Event hooks (additive):**
   - Publish: call `notify_homework_published(homework)` alongside the existing
     `create_notification` loop in `HomeworkCreateView.post`
     (`homework/views.py`, the per-student notification block).
   - Submission: call `notify_submission_result(submission)` after
     `submission.save()` / score recalc in `StudentHomeworkTakeView.post`
     (`homework/views.py`). Both wrapped so an exception never breaks the
     request (log + continue).
5. **Webhook:** register `/whatsapp/webhook/` in Meta; verify with
   `WHATSAPP_WEBHOOK_VERIFY_TOKEN`; validate signature with app secret.
6. **Env (all inert until set):** `WHATSAPP_PROVIDER=meta_cloud`,
   `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`,
   `WHATSAPP_APP_SECRET`. Absent → feature stays disabled.
7. **Go-live (prod):** Meta Business verification → WABA + number → submit &
   approve the two utility templates → set `WhatsAppTemplate.is_active=True` →
   HoI enables via SchoolWhatsAppSettings → collect parent opt-ins.
8. **Rollback:** flip global `is_enabled=False` (instant kill switch); columns
   and tables are additive and can remain. No destructive migration.

### CI wiring (mandatory — CI is opt-in per app)

`.github/workflows/ci.yml` has **no auto-discovery**; each app gets a dedicated
job. A new `whatsapp/tests/` directory is invisible to CI until wired, so green
PRs would prove nothing (same gap as the outstanding `ai_import` CI job). Sprint
1 must:

- Add a `whatsapp-tests` job to `.github/workflows/ci.yml` running
  `pytest whatsapp/tests/ -n auto --dist=loadscope`.
- Add the Playwright specs to the existing `ui-tests` job path
  (`tests/e2e/test_whatsapp.py` / `ui_tests/`).
- Add `whatsapp/tests` to `pytest.ini` `testpaths` for local discovery.
- The `migration-check` job (`tests_migrations.py`) runs automatically and will
  validate the two new migrations — no wiring needed there.

## Out of scope

- **Group posting** to real WhatsApp groups (official API can't; column stored
  only). Unofficial backend is a stub.
- **SMS / email-as-WhatsApp-fallback** — WhatsApp only this epic.
- **Inbound conversational replies / two-way support** beyond STOP opt-out.
- **Marketing/broadcast templates** — utility only.
- **Teacher-facing delivery UI** beyond triggering.
- **Daily digest template** (noted as a future cost lever, not built now).
- **Media/PDF attachments** in messages (text templates only).
- **Per-parent language selection** beyond a single template locale.

## Sprint breakdown

### Sprint 1 — Foundation & provider (inert)
- CPP-XXX: Create `whatsapp` app + models (`WhatsAppConfig`,
  `WhatsAppPreference`, `WhatsAppTemplate`, `WhatsAppMessageLog`) + migrations.
- CPP-XXX: `WhatsAppProvider` abstraction + `meta_cloud` backend + env wiring
  (provider selectable, no live calls in tests).
- CPP-XXX: `ClassRoom.whatsapp_group_id` migration.
- CPP-XXX: Seed global disabled config + inactive templates.
- CPP-XXX: Unit tests — provider mocked, gate/resolution logic.
- CPP-XXX: **Wire CI** — add `whatsapp-tests` job to `ci.yml`, add path to
  `ui-tests` job, add `whatsapp/tests` to `pytest.ini` testpaths.

### Sprint 2 — Recipient resolution & sends
- CPP-XXX: `_resolve_parent_phone` fallback chain + dedupe + E.164 validation.
- CPP-XXX: `notify_homework_published` service + RQ task + log lifecycle.
- CPP-XXX: `notify_submission_result` service (final-submission-only) + task.
- CPP-XXX: Hook both into `HomeworkCreateView` / `StudentHomeworkTakeView`
  (exception-isolated).
- CPP-XXX: Unit + integration tests for both events (mocked provider).

### Sprint 3 — Delivery tracking & opt-in
- CPP-XXX: `WhatsAppWebhookView` (verification + status callbacks +
  signature validation) + `apply_delivery_event` precedence.
- CPP-XXX: `ParentWhatsAppPrefsView` opt-in/number-confirm (HTMX).
- CPP-XXX: `WhatsAppUnsubscribeView` tokenised opt-out + inbound STOP handling.
- CPP-XXX: Tests — webhook payloads, opt-in gating, status precedence.

### Sprint 4 — Admin visibility & go-live
- CPP-XXX: `SchoolWhatsAppSettingsView` (HoI enable + event toggles).
- CPP-XXX: `WhatsAppDeliveryLogView` (HoI school-wide, HoD dept-scoped) +
  unreachable-parents gaps view.
- CPP-XXX: Per-school throttle / tier-limit backoff handling.
- CPP-XXX: Go-live runbook (Meta verification, template submission, env, opt-in
  collection) + Playwright UI tests for prefs/settings.
