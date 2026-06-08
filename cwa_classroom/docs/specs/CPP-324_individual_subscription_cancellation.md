# CPP-324: Add Subscription Cancellation for Individual/Student Subscribers

## Problem

Head-of-Institute (HoI) subscribers can cancel their subscription in-app via
`InstituteCancelSubscriptionView` (a "Cancel Subscription" button + danger
confirm modal on the institute dashboard). Individual/student subscribers had
no equivalent: the parent/student billing page (`templates/parent/billing.html`)
only *displayed* status and a passive "Subscription will cancel on…" note. Its
only actions were **View Invoices** and **Payment History** — there was no way
to actually cancel.

The individual `Subscription` model already supports `cancel_at_period_end`, so
the gap was purely the view + route + UI to trigger a Stripe cancellation.

## Fix

Mirror the proven institute cancellation pattern for the individual
`Subscription` (a `OneToOneField` on the user).

### 1. New view — `IndividualCancelSubscriptionView`

`billing/views.py`. `LoginRequiredMixin`, POST-only. Operates on
`request.user.subscription`:

- No subscription / no `stripe_subscription_id` → friendly error message, no
  Stripe call, redirect back to `parent_billing`.
- Otherwise calls
  `billing.stripe_service.cancel_subscription(sub.stripe_subscription_id, at_period_end=True)`.
- On success: locally sets `cancel_at_period_end = True` and
  `cancelled_at = now()` as a safety net (the
  `customer.subscription.updated/deleted` webhook also keeps this in sync, but
  setting it inline means the UI reflects the change immediately even if the
  webhook is delayed). Shows a success message and audit-logs via
  `log_event(category='billing', action='subscription_cancelled', detail={'subscription_id': ...})`.
- `stripe.error.StripeError` is caught and surfaced as a non-fatal message
  (no 500).

Because the subscription is a `OneToOne` on the requesting user, there is no
cross-account vector: a user can only ever cancel their own subscription.

### 2. New route

`billing/urls.py`:

```
path('billing/cancel-subscription/', views.IndividualCancelSubscriptionView.as_view(), name='cancel_subscription'),
```

### 3. Template — `templates/parent/billing.html`

- Shows a **Cancel Subscription** button (danger styling) + the shared confirm
  modal **only** when `subscription.is_active_or_trialing` **and**
  `not subscription.cancel_at_period_end`.
- When `cancel_at_period_end` is already set, the existing amber
  "Subscription will cancel on {date}" note is shown instead of the button
  (prevents double-cancel).
- Reuses the existing Alpine confirm-modal pattern
  (`templates/partials/confirm_modal.html`).

## Files Changed

- `billing/views.py` — `IndividualCancelSubscriptionView`
- `billing/urls.py` — `cancel_subscription` route
- `templates/parent/billing.html` — cancel button + confirm modal
- `billing/tests_cancel_subscription.py` — unit tests (pytest-django via Django `TestCase`)
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

Unit (`billing/tests_cancel_subscription.py`):

- `test_individual_cancel_sets_cancel_at_period_end`
- `test_individual_cancel_logs_audit_event`
- `test_individual_cancel_no_active_subscription_errors`
- `test_individual_cancel_stripe_error_handled`
- `test_individual_cancel_only_affects_own_subscription` (isolation)
- `test_individual_cancel_requires_login`

UI (`ui_tests/test_billing_cancel.py`):

- `test_parent_cancels_subscription` (button → modal → confirm → "will cancel" state)
- `test_cancel_button_hidden_when_no_active_sub`
- `test_cancel_button_hidden_when_already_cancelling`
