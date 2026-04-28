# billing

Payments, subscriptions, discounts, and entitlements. Two parallel tracks:

1. **Individual student** — one-off / recurring packages purchased via Stripe Checkout (`Package` → `Payment`).
2. **Institute / school** — monthly billing for a whole school (`InstitutePlan` → `SchoolSubscription`), with metered invoicing limits, plan changes, and module add-ons.

The app also owns discount and promo codes, the Stripe webhook handler, and the entitlement layer that other apps consult before granting access to gated features.

## Key models

**Plans & subscriptions**
- **Package** — student tier (name, price, class_limit, trial_days, stripe_price_id).
- **InstitutePlan** — school tier (class/student/yearly-invoice limits, overage rates).
- **Subscription** — Stripe-backed subscription lifecycle (status, stripe_subscription_id, trial_end, current_period_end).
- **SchoolSubscription** — an `InstitutePlan` instance attached to a specific `School`.
- **ModuleProduct** / **ModuleSubscription** — paid add-on modules (e.g. `ai_import_*`, attendance modules) attached to a subscription.

**Discounts**
- **DiscountCode** — student codes (% off or fully free, usage limits).
- **InstitueDiscountCode** — school codes; can override plan limits.
- **PromoCode** — time-limited promotional codes with `grant_days` and class limits.

**Payments**
- **Payment** — legacy PaymentIntent records (`pending` / `succeeded` / `failed` / `refunded`).

## URL prefix & key routes

Mounted at the project root.

- `billing/checkout/<package_id>/` — student Stripe checkout
- `billing/institute/plans/`, `billing/institute/checkout/` — school plan selection & purchase
- `billing/institute/change-plan/` — upgrade/downgrade
- `billing/portal/` — Stripe customer portal
- Admin routes under `/admin-dashboard/billing/...` for super-admin management
- Stripe webhook endpoint (consumes `STRIPE_WEBHOOK_SECRET`)

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'billing', ...]

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_CURRENCY = os.environ.get('STRIPE_CURRENCY', 'usd')

# Per-module Stripe price IDs (slug → stripe_price_id)
MODULE_STRIPE_PRICES = {
    'teachers_attendance': os.environ.get('STRIPE_PRICE_TEACHERS_ATTENDANCE', ''),
    'students_attendance': os.environ.get('STRIPE_PRICE_STUDENTS_ATTENDANCE', ''),
    'student_progress_reports': os.environ.get('STRIPE_PRICE_PROGRESS_REPORTS', ''),
}
```

In root `urls.py`:

```python
path('', include('billing.urls')),
```

## Entitlement API

Other apps gate access via the entitlements module rather than reading Subscription/Module rows directly:

```python
from billing.entitlements import has_module_access, check_plan_limit
```

This is the integration surface for plan-aware features.

## Dependencies

- **accounts** — `CustomUser` is the payer / subscriber.
- **classroom** — `School` and `Department` own the subscription scope.
- **audit** — billing events are recorded via `audit.services.log_event`.

## External services

- **Stripe** — Checkout sessions, subscriptions, webhooks, customer portal.
