# CPP-324: Add Subscription Cancellation for Individual/Student Subscribers

## Problem

Head-of-Institute (HoI) subscribers can cancel their subscription in-app via
`InstituteCancelSubscriptionView` (a "Cancel Subscription" button + danger
confirm modal on the institute dashboard). Individual/student subscribers had
no equivalent: their billing page (`billing_history`, linked from the student
sidebar) only displayed package and status, and the parent billing page
(`templates/parent/billing.html`) only showed a passive "Subscription will
cancel on…" note.

The individual `Subscription` model already supports `cancel_at_period_end`, so
the gap was purely the view + route + UI to trigger a Stripe cancellation.

## Who owns an individual Subscription

The personal `Subscription` (OneToOne on the user) is created during
**individual student registration** (`IndividualStudentRegisterView` /
`_create_account_from_pending`, role `INDIVIDUAL_STUDENT`). Parents normally
pay invoices rather than holding a subscription, but `ParentBillingView`
renders the same subscription card for parents who do hold one. The cancel UI
therefore lives on **both** surfaces via a shared partial:

- `templates/billing/billing_history.html` — the individual student's billing
  page (sidebar → Billing). Primary surface.
- `templates/parent/billing.html` — parent billing page, for parents with a
  personal subscription.

## Fix

### 1. New view — `IndividualCancelSubscriptionView`

`billing/views.py`. `LoginRequiredMixin`, POST-only. Operates on
`request.user.subscription`:

- No subscription / no `stripe_subscription_id` → friendly error message, no
  Stripe call.
- Already `cancel_at_period_end` → info message, no Stripe call (double-cancel
  guard, server side).
- Otherwise calls
  `billing.stripe_service.cancel_subscription(sub.stripe_subscription_id, at_period_end=True)`.
- On success: locally sets `cancel_at_period_end = True` and
  `cancelled_at = now()` as a safety net (the
  `customer.subscription.updated/deleted` webhook also keeps this in sync, but
  setting it inline means the UI reflects the change immediately even if the
  webhook is delayed). Shows a success message and audit-logs via
  `log_event(category='billing', action='subscription_cancelled', detail={'subscription_id': ...})`.
- `stripe.error.StripeError` is caught and surfaced as a non-fatal message
  (no 500); local state is NOT flipped on failure.
- All paths redirect role-aware via `_billing_page()`: `PARENT` →
  `parent_billing`, everyone else (individual students) → `billing_history`.

Because the subscription is a `OneToOne` on the requesting user, there is no
cross-account vector: a user can only ever cancel their own subscription.

### 2. New route

`billing/urls.py`:

```
path('billing/cancel-subscription/', views.IndividualCancelSubscriptionView.as_view(), name='cancel_subscription'),
```

### 3. Shared template partial

`templates/billing/_partials/cancel_subscription.html` — self-contained
(own Alpine `confirmModal()` scope wrapping trigger + modal + script), included
with `{% include ... with sub=<subscription> %}` from both billing pages:

- Shows the **Cancel Subscription** button (danger confirm modal) only when
  `sub.is_active_or_trialing` **and** `sub.stripe_subscription_id` **and**
  `not sub.cancel_at_period_end`.
- When `cancel_at_period_end` is set, shows the amber "will cancel on {date}"
  note instead (UI double-cancel guard). The date falls back
  `current_period_end` → `trial_end` → generic wording, so trialing
  subscriptions without a period end never render a blank date.

## Files Changed

- `billing/views.py` — `IndividualCancelSubscriptionView` (+ role-aware redirect)
- `billing/urls.py` — `cancel_subscription` route
- `templates/billing/_partials/cancel_subscription.html` — shared cancel section (new)
- `templates/billing/billing_history.html` — period-end row + cancel partial for `individual_sub`
- `templates/parent/billing.html` — cancel partial replaces passive note
- `billing/tests_cancel_subscription.py` — unit tests (Django `TestCase`, run via pytest)
- `ui_tests/test_billing_cancel.py` — Playwright UI tests
- `docs/specs/CPP-324_individual_subscription_cancellation.md` — this spec

> Note on file locations: the Jira AC named `billing/tests/test_views_cancel.py`
> and `tests/e2e/test_billing_cancel.py`. The repo's actual conventions are flat
> `billing/tests_*.py` (Django `TestCase`) and `ui_tests/test_*.py` (Playwright),
> so the tests follow the real conventions to ensure they are collected and run.

## Permission Model

- Any authenticated user with a `Subscription` may cancel their own
  subscription (`LoginRequiredMixin`). Matches `InstituteCancelSubscriptionView`,
  which is also login-gated rather than role-gated.
- No object is fetched by id; the target is always `request.user.subscription`,
  so cross-tenant/cross-account cancellation is structurally impossible.

## Migration Notes

None. No model changes — `cancel_at_period_end`, `cancelled_at`,
`current_period_end`, `stripe_subscription_id` already exist on `Subscription`.

## Test Coverage

Unit (`billing/tests_cancel_subscription.py`, 9 tests):

- `test_individual_cancel_sets_cancel_at_period_end` (asserts redirect → `billing_history`)
- `test_parent_cancel_redirects_to_parent_billing`
- `test_individual_cancel_logs_audit_event`
- `test_individual_cancel_no_active_subscription_errors`
- `test_individual_cancel_no_stripe_id_errors`
- `test_individual_cancel_already_cancelling_is_noop`
- `test_individual_cancel_stripe_error_handled` (state not flipped on failure)
- `test_individual_cancel_only_affects_own_subscription` (isolation)
- `test_individual_cancel_requires_login`

UI (`ui_tests/test_billing_cancel.py`, 4 tests):

- `test_individual_student_cancels_subscription` — INDIVIDUAL_STUDENT role on
  `/billing/history/`: button → modal → confirm → lands back on the page in
  the "will cancel on …" state
- `test_cancel_button_hidden_when_no_active_sub`
- `test_cancel_button_hidden_when_already_cancelling`
- `test_parent_cancels_subscription_from_parent_billing` — parent holding a
  personal subscription cancels from `/parent/billing/`
