# SPEC — School Student Payment Onboarding (CPP-300)

## Problem / root cause

`CustomUser.profile_completed` defaults to **`True`** (`accounts/models.py`,
migration `accounts/0004_add_profile_completion_fields.py`). The CSV student
importer created accounts without overriding it, so imported students were
considered "onboarded" the moment they were created.

Consequences:

- `ProfileCompletionMiddleware` never sent imported students through
  `CompleteProfileView`, so they **skipped the first-login payment/discount
  gate** entirely.
- With no personal `billing.Subscription`, the ANY-school entitlement logic
  (`billing/entitlements.py`) let them ride their **school's** `InstitutePlan`
  — frequently the unlimited "Platinum" plan — giving free full access that was
  never paid for.

CPP-300 closes the free-access door and routes every imported student through a
hard-blocked first-login flow where they either redeem a discount code or enter
card details.

## Scope (5 parts)

### 1. Auto-send welcome emails on import (published schools)
`StudentCSVConfirmView` (`classroom/views.py`) calls
`email_service.send_school_publish_notifications(school)` after a successful
`execute_import`, **only when `school.is_published`**. That notifier already
emails just the `SchoolStudent` / `SchoolTeacher` rows with
`notified_at IS NULL` (i.e. the just-imported people), includes the
`pending_password`, then clears it and stamps `notified_at` +
`welcome_email_sent`. Because of the `notified_at IS NULL` filter, a later
**Publish** never re-sends to people already notified at import — no double-send.

Unpublished schools are unchanged: nothing is emailed at import; credentials go
out when the admin publishes. The import results page
(`templates/admin/csv_student_results.html`) shows which case happened.

### 2. Per-class bulk "Resend Welcome"
A **Resend Welcome** button on the class detail page
(`templates/teacher/class_detail.html`) opens a modal listing all active
students, **all checked by default**, with Select all / Unselect all, a live
"Resend to N of M" count, submit disabled at 0, and a confirm dialog (it
regenerates passwords). `BulkResendWelcomeView`
(`classroom/views_password_admin.py`, route `class_bulk_resend_welcome`) resends
to each selected **student and each of their active linked parents**
(`ParentStudent`), regenerating temporary credentials for institute accounts via
the shared `_resend_welcome_to_user(user, school)` helper. Recipients with no
email are skipped and reported. Standard POST → redirect → messages summary (no
HTMX — it's a multi-second multi-send). Tenant isolation: the class is resolved
against the requesting user's school / taught classes, so a cross-school id 404s.

Roles: Admin / Institute Owner / HoI (any class in their school) and the class's
own teachers (HoD via department head, teachers via `ClassTeacher`).

### 3. Imported students are gated (keystone)
`import_services.execute_import` now creates each new **student** with
`profile_completed=False`, `must_change_password=True`,
`creation_method='institute'`, and creates **no** `billing.Subscription`.
Imported **parents** also get `creation_method='institute'` so the welcome /
resend emails attach their credentials.

### 4. First-login hard block (already present — verified)
`ProfileCompletionMiddleware` blocks any user with `must_change_password=True`
or `profile_completed=False` to `CompleteProfileView`.
`accounts/complete_profile.html` already surfaces both the **discount code**
field and the **card / subscription** step. Behaviour:

- 100% (`is_fully_free`) discount code → activates an active `Subscription`
  immediately, no card.
- Partial / no code → Stripe Checkout, passing the code's `stripe_coupon_id` so
  only the remaining balance is charged.

No new "first login" field was added — Django's built-in `last_login`
(`None` = never logged in) plus `profile_completed` are sufficient.

### 5. Reset command for the existing Platinum-default bug
`billing/management/commands/reset_imported_student_gating.py` re-gates already
imported students.

**Predicate (authoritative = the Subscription row):** re-gate a `Role.STUDENT`
with `profile_completed=True` iff they have **no** `billing.Subscription` in
`active`/`trialing` status. Students who redeemed a 100%-off code have an active
free subscription and are **not** re-gated. `stripe_customer_id` is a secondary
signal only — anyone who paid already has an active/trialing subscription.

Never touches staff, parents, or individual students. Skips users already
`profile_completed=False` (idempotent). `--dry-run` prints exact counts + a
sample and writes nothing.

#### Runbook
```bash
# Preview — no writes
python manage.py reset_imported_student_gating --dry-run

# Apply
python manage.py reset_imported_student_gating
```
Safe to re-run; a second run reports "No students need re-gating."

## Data / flow notes

- **No schema change / no migration.** Everything reuses existing fields
  (`profile_completed`, `must_change_password`, `creation_method`,
  `SchoolStudent.pending_password`, `notified_at`, `last_login`).
- Email side effects are the source of truth for "was the welcome sent":
  `notified_at` stamped + `pending_password` cleared.

## Tests

- `classroom/tests/test_csv_student_import.py` — `ImportGatingTests`,
  `ImportAutoSendWelcomeTests` (gating fields, no subscription, published
  auto-send, unpublished hold, no double-send).
- `classroom/tests/test_bulk_resend_welcome.py` — bulk resend incl. parent
  fan-out, selection scoping, no-email skip, tenant isolation, permissions.
- `billing/tests_reset_imported_student_gating.py` — reset predicate, free-code
  guard, staff/parent/individual exclusions, dry-run, idempotency.
- `accounts/tests.py::CPP300_CompleteProfileStripeEnforcementTest` — hard-block
  redirect, 100% code free activation, partial-code coupon redirect.
- `ui_tests/test_cpp300_import_onboarding.py` — two end-to-end browser
  scenarios (published import → email → student login → gate; unpublished import
  → publish → email → student login → gate).

## Known follow-up

Two welcome-email templates are in play: Part 1 reuses
`email/transactional/school_published.html`; Part 2 reuses the
`notifications.services` lifecycle templates. This was an intentional
lowest-risk choice for CPP-300 — consolidate onto one template family in a
follow-up ticket.
