# Invoice Email Delivery Status (CPP-343)

## Overview

Surfaces *whether an invoice email actually reached the recipient* in the invoicing dashboard — not just the invoice's issued/draft/cancelled status. Admins can see at a glance if a delivery succeeded, bounced, or failed; resend after fixing a bad address; and read the failure reason when something went wrong.

The dashboard piece is powered by a delivery-tracking backend: every email sent through Resend now records its provider message id, and a Svix-verified webhook updates each `EmailLog` as Resend reports `delivered` / `bounced` / `complained` / `opened` / `clicked`. A cron command flags emails that were accepted but never confirmed delivered.

Scope note: all mail is sent from a single Resend-verified domain (`DEFAULT_FROM_EMAIL`); the school's `outgoing_email` is only CC/Reply-To. Because we own the sending domain, the full Resend webhook signal set is available.

## Access Control

Reuses the existing invoicing roles — no new permissions.

| Role | See delivery status | Resend |
|------|---------------------|--------|
| Institute Owner | Own schools | Yes |
| Head of Institute | Own schools | Yes |
| Accountant | Assigned schools | Yes |

The webhook endpoint is unauthenticated but Svix-signature-verified (shared secret), and CSRF-exempt.

## Data Model

`classroom.EmailLog` gains delivery-tracking fields (all additive, nullable/blank — safe migration):

- `provider_message_id` — `CharField(max_length=255, blank=True, db_index=True)`. The Resend `email_id`; correlation key for webhooks.
- `STATUS_CHOICES` expands from `sent`/`failed` to: `sent`, `delivered`, `bounced`, `complained`, `delayed`, `opened`, `clicked`, `failed`.
- Per-event timestamps: `delivered_at`, `bounced_at`, `complained_at`, `opened_at`, `clicked_at` (all `DateTimeField(null=True, blank=True)`).
- `bounce_reason` — `TextField(blank=True)`.
- `status_updated_at` — `DateTimeField(null=True, blank=True)`.

**Status rank guard.** Webhook updates only advance status by rank, so a late `opened` event can't overwrite a terminal `bounced`. Rank: `sent` < `delayed` < `opened` < `clicked` < `delivered` < `complained` = `bounced` = `failed`.

## Backend

- **`ResendEmailBackend._send`** captures the id from `resend.Emails.send()` and stashes it on the message (`message.resend_message_id`).
- **`email_service.send_templated_email`** reads `getattr(msg, 'resend_message_id', '')` after `msg.send()` and records it on the `EmailLog`. (This is the path that creates invoice `EmailLog`s.)
- Other senders that don't create an `EmailLog` (billing notifications via `send_mail`) are unaffected; their webhook events simply find no matching row and are ack'd.

## Webhook

- **`/webhooks/resend/`** (`ResendWebhookView`, POST, CSRF-exempt, Svix-verified via `RESEND_WEBHOOK_SECRET`).
- Maps `email.delivered` / `email.bounced` / `email.complained` / `email.delivery_delayed` / `email.opened` / `email.clicked` to status + timestamp.
- Looks up `EmailLog` by `provider_message_id`. Unknown id → `202` (ack, stop retries). Untracked event type → `204`. Bad signature → `400`.
- New setting `RESEND_WEBHOOK_SECRET` (env). New dependency `svix`.

## Reconciliation

- **`flag_undelivered_emails`** management command (mirrors `process_email_queue`, runs on cron). Flags `EmailLog`s with `status='sent'`, a non-empty `provider_message_id`, and `sent_at` older than a threshold (default 20 min) that never advanced to a delivered/opened/clicked/bounced state. Logs a warning report; `--minutes` and `--dry-run` options.

## Dashboard

- **`InvoiceListView`** (`/invoicing/`) — annotates each invoice with its latest `EmailLog` and shows an **Email** column: coloured pill (Delivered/Opened green, Sent/Delayed grey, Bounced/Failed red, "—" when never emailed). Failed/bounced rows keep the existing Resend action.
- **`InvoiceDetailView`** — the existing Email History panel is upgraded from binary sent/failed to the full status set, showing per-event timestamp and `bounce_reason` on failure.

## Welcome emails

The same delivery tracking is extended to welcome emails:

- **Staff welcome email** (`email_utils.send_staff_welcome_email`) previously sent via `EmailMultiAlternatives` with no `EmailLog` — it now writes a tracked `EmailLog` (`notification_type='welcome'`, with `provider_message_id`), so it receives webhook updates like every other email. Welcome/resend-welcome notifications already route through `send_templated_email` and were tracked once `provider_message_id` was added.
- **`email_service.get_welcome_email_states(user_ids)`** returns each user's latest welcome-email delivery state (`delivered`/`sent`/`bounced`/`failed`), collapsing `welcome` + `welcome_resend` logs. Welcome emails have a single recipient, so the most-recent log per user is authoritative.
- **Admin user lists** — teachers (`school_teachers.html`), students (`partials/students_table.html`) and parents (`partials/parents_table.html`) upgrade the existing "Welcome sent / not sent" chip to show the tracked delivery state via the shared `partials/_welcome_email_badge.html`, falling back to the `welcome_email_sent` flag when no log exists. The teacher/student views annotate each page row with `welcome_email_state` (`_annotate_welcome_email_state` in `views_admin.py`); the parents list (`views_parent_admin.SchoolParentListView`) builds dict rows, so it annotates account rows inline. Guardian-only contacts have no account/welcome email and show nothing.
- **Parents list welcome filter** — `?welcome=sent|not_sent|bounced|failed` on the parents page (HTMX dropdown beside the search). Classification is driven by the latest welcome `EmailLog` (genuine proof the email went out) via `_parent_welcome_filter_state`, falling back to `welcome_email_sent` only for legacy accounts. "Sent" = delivered or accepted; a **bounced** welcome email is deliberately excluded from "Sent" so a bounce is never read as a successful send.

## Tests

- **pytest-django:** model status-rank guard + timestamp setting; backend id capture; webhook (valid signature updates log, bad signature 400, unknown id 202, rank guard, each event type); reconciliation command (flags stale, ignores delivered, respects `--minutes`); invoice list annotation + tenant isolation.
- **Playwright:** dashboard Email column renders per status; detail panel shows delivered/bounced states and reason; resend control still works.
