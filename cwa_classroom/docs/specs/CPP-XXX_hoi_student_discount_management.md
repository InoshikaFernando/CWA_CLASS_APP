# SPEC — HoI Student Discount Management (CPP-XXX)

## Overview

HoIs need visibility and control over which of their school's students are on a
discount and which are paying. Today a student's discount is **implicit** — it
lives only in the shape of their `billing.Subscription` (a free active sub with
no Stripe subscription = 100% code; a Stripe coupon = partial; a plain paid sub
= full) and the code they typed at onboarding is **not recorded anywhere**. This
feature (1) records the redeemed discount on the subscription so it is queryable,
(2) shows each student's discount state on the existing school-students page, and
(3) lets an HoI **clear** a student's discount, which re-gates them so on next
login they pay the full amount (entering card details if none on file).

## User stories

- **As an HoI**, I want to see which of my students have a discount code (and
  what kind), so I can spot who is on free/discounted access vs paying.
- **As an HoI**, I want to clear a student's discount code, so that the student
  is required to pay the full amount on their next login.
- **As an Institute Owner / Admin**, I want the same, scoped to my school(s).
- **As an HoD**, I want the same but limited to students in my department's
  classes.
- **As a Teacher**, I can *see* discount state for students in my classes (read
  only) but **cannot clear** — clearing is a billing action reserved for
  institute leadership.
- **As a Student/Parent**, I have **no access** to this view (explicitly
  excluded).

## Data model

The redeemed discount is currently unrecorded. Add a snapshot to the existing
`billing.Subscription` (do **not** add to `CustomUser` — anti-pattern):

```python
class Subscription(models.Model):
    ...
    # Discount snapshot — set when the student redeems a code at the
    # CompleteProfileView gate. NULL = no discount (paying full / none recorded).
    discount_code = models.ForeignKey(
        'billing.DiscountCode',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='redeemed_subscriptions',
        help_text='Discount code redeemed for this subscription, if any.',
    )
    discount_percent_snapshot = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Percent off at redemption (100 = fully free). Snapshot so '
                  'history survives later edits to the DiscountCode.',
    )
    discount_cleared_at = models.DateTimeField(null=True, blank=True)
    discount_cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
```

- `Subscription` already has a `user` (OneToOne) → tenant scoping is via the
  user's `SchoolStudent` rows (see Permissions).
- Money stays out of this model; `discount_percent_snapshot` is an integer
  percent, not a price.
- `CompleteProfileView` is updated to set `discount_code` +
  `discount_percent_snapshot` whenever a code is redeemed (both the 100%-free
  path and the partial-coupon path).

### Backfill (existing rows)

A one-off, idempotent management command `backfill_subscription_discounts`
infers state for existing subscriptions where `discount_code IS NULL`:

| Observed state | Inferred discount state |
| --- | --- |
| `status` active/trialing **and** `stripe_subscription_id == ''` | **100% free** (`discount_percent_snapshot = 100`, `discount_code` left NULL — code unknown) |
| `stripe_subscription_id` set **and** Stripe sub has a `discount`/coupon | **partial** (`discount_percent_snapshot` = coupon percent_off) |
| `stripe_subscription_id` set, no coupon | **none / full** (leave NULL) |

Stripe lookups are read-only and batched; `--dry-run` prints counts only.

## Resolution / inheritance rules — "what discount state is a student in?"

Resolved per student from their `Subscription` (authoritative once recorded):

1. **No subscription** (or not active/trialing) → `NONE`.
2. `discount_percent_snapshot == 100` → `FREE_100`.
3. `0 < discount_percent_snapshot < 100` → `PARTIAL` (show the percent).
4. Otherwise (active sub, no recorded discount) → `FULL`.

**Legacy-paid guard (required).** For rows with no snapshot yet, the *legacy*
inference "active + empty `stripe_subscription_id` ⇒ free" is **wrong** for
students who paid through the removed one-time PaymentIntent flow — they are also
active with no Stripe subscription, yet they paid. The rule therefore is:

> infer `FREE_100` only if (active **and** empty `stripe_subscription_id`
> **and** the user has **no** succeeded `billing.Payment`). If a succeeded
> `Payment` exists, classify as `FULL`.

This stops a paying student being shown as discounted (and then wrongly cleared,
cancelling access they already paid for). Applies to both the live
`discount_state` fallback and the backfill command.

Expose `Subscription.discount_state` returning `{none, free_100, partial, full}`
so views/templates don't re-derive it. It reads only local fields + a cheap
`Payment` existence check — never a Stripe API call.

## Views, URLs, templates

Extend the existing school-students page rather than build a new dashboard.

| View | URL name | Method | Notes |
| --- | --- | --- | --- |
| `SchoolStudentManageView` (existing) | `admin_school_students` | GET | Add a **Discount** column (badge per `discount_state`) + a `?discount=` filter (`all` / `free_100` / `partial` / `full` / `none`). |
| `StudentDiscountClearView` (new) | `student_discount_clear` | POST | HTMX partial. Clears one student's discount, returns the updated row. |
| `_partials/student_discount_cell.html` (new) | — | — | HTMX partial: badge + (for privileged roles) a "Clear discount" button with a confirm. |

Templates: `admin_dashboard/school_students.html` (column + filter),
`admin_dashboard/_partials/student_discount_cell.html` (HTMX swap target).

### Clear flow (`StudentDiscountClearView.post`)

Within a transaction, for the target student (tenant-checked):

1. **Cancel the discounted access.** If the sub is a 100%-free sub
   (`stripe_subscription_id == ''`): set `status = cancelled`. If it is a
   partial Stripe subscription: cancel it in Stripe
   (`stripe.Subscription.delete`, or remove the coupon then cancel) and set
   `status = cancelled`.
2. Clear the snapshot: `discount_code = None`, `discount_percent_snapshot = None`,
   stamp `discount_cleared_at` / `discount_cleared_by`.
3. **Re-gate:** `user.profile_completed = False` → `ProfileCompletionMiddleware`
   funnels the student through `CompleteProfileView` on next login, where with
   **no code** they pay the **full** amount via `create_student_checkout_session`
   (Stripe Checkout, subscription mode — **never** the legacy PaymentIntent flow,
   which was removed in CPP-XXX / PR #499).
4. `log_event(action='student_discount_cleared', detail={student, old_state,
   old_percent})` for the audit trail.
5. **Notify the student (and active linked parents)** by email that their
   discount was removed and payment is now required on next login. Queue it (do
   not send in-request); skip recipients with no email and report it.

"Enter card if none / charged full if partial" is automatic: the gate's checkout
collects a card and bills the full package price because no code is applied.

**Institute-leadership only.** Per product decision, only HoI / Institute Owner
/ Admin can clear a discount — HoDs and teachers cannot (the clear view's
`required_roles` excludes them, and the list hides the Clear button for them).
`_get_school` already scopes an HoI/Owner to their own school and an Admin to any
school, so no extra per-student check is needed.

## Permissions

Default deny. Reuse `SchoolStudentManageView._get_school` tenant scoping.

Managing subscriptions (clearing discounts) is **institute-leadership only** —
HoI / Institute Owner / Admin. HoDs and teachers can *see* the state but cannot
clear (per product decision: only HoI add/remove subscriptions).

| Role | See discount column | Clear discount |
| --- | --- | --- |
| Admin / superuser | ✅ any school | ✅ |
| Institute Owner | ✅ own school | ✅ |
| Head of Institute | ✅ own school | ✅ |
| Head of Department | ✅ (read only) | ❌ |
| Teacher | ✅ class students (read only) | ❌ |
| Parent / Student | ❌ | ❌ |

`StudentDiscountClearView` requires `[Admin, Institute Owner, Head of Institute]`
**and** the student must resolve within the actor's school (via `_get_school`),
else 404.

## Edge cases

- **Tenant isolation:** a student id outside the actor's school/department → 404.
  Never trust the posted id; resolve via `_get_school` + `SchoolStudent`.
- **No subscription / not onboarded:** `discount_state = none`; "Clear" is hidden
  / no-op.
- **Already paying full:** "Clear" is hidden (nothing to clear).
- **Partial coupon mid-period:** cancelling re-gates immediately; document that
  the student loses access until they re-pay (acceptable — that is the intent).
  Optionally cancel at period end instead (out of scope v1; note it).
- **Stripe error during clear:** abort the transaction, surface a clear message,
  leave the student unchanged (no half-cleared state).
- **Individual students:** out of scope — this view is school students only.
- **Currency:** read from existing currency config; no hardcoded `$`.
- **Idempotency:** clearing an already-cleared student is a safe no-op.

## Migration & rollout

1. Migration: add `discount_code`, `discount_percent_snapshot`,
   `discount_cleared_at`, `discount_cleared_by` to `Subscription` — all nullable,
   additive, no data loss, reversible.
2. Ship `CompleteProfileView` change to record the discount going forward.
3. Run `backfill_subscription_discounts --dry-run` then apply, to populate state
   for existing students.
4. No feature flag needed (additive UI, deny-by-default). Rollback = revert the
   view/template + the migration (additive, safe to reverse).

## Out of scope

- **Assigning / applying** a discount code from this UI (owner asked only for
  *see* + *clear*). Note as a likely fast-follow.
- **Bulk clear** — `reset_imported_student_gating` already covers bulk re-gating.
- Individual (non-school) students.
- Changing the partial-discount amount (vs. clearing it entirely).
- Cancel-at-period-end semantics for partial subs (v1 cancels immediately).

## Sprint breakdown

### Sprint 1 — Record & display (≈5 stories)
- CPP-XXX: Add discount snapshot fields to `Subscription` (+ migration).
- CPP-XXX: Record discount in `CompleteProfileView` (100% + partial paths).
- CPP-XXX: `Subscription.discount_state` property + unit tests.
- CPP-XXX: Discount column + filter on `admin_school_students` (badge per state).
- CPP-XXX: `backfill_subscription_discounts` command (+ `--dry-run`, tests).

### Sprint 2 — Clear action (≈5 stories)
- CPP-XXX: `StudentDiscountClearView` + URL + HTMX partial (free-100 path).
- CPP-XXX: Partial-coupon path — cancel Stripe sub / remove coupon.
- CPP-XXX: Re-gate (`profile_completed=False`) + audit logging.
- CPP-XXX: Permission matrix enforcement + tenant-isolation tests.
- CPP-XXX: Playwright UI test — HoI clears a discount → student hits the gate →
  pays full via Stripe Checkout (mocked).
