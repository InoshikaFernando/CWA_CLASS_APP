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
# No currency setting: subscriptions are always charged in USD
# (billing.stripe_service.SUBSCRIPTION_CURRENCY), and school invoices bill in
# the school's own default_currency.

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

## Currency — subscriptions are always USD

Student packages, institute plans and module add-ons are charged in **USD**, pinned
as `billing.stripe_service.SUBSCRIPTION_CURRENCY`. There is deliberately no
`STRIPE_CURRENCY` env setting: an env knob is what once minted an NZD 19 Stripe
price for a $19 package, and a student was charged NZD 19.

Nothing in a checkout call names a currency. Stripe Prices are immutable and carry
their own, so the currency a card is charged is decided entirely by the Price
attached to `Package.stripe_price_id` / `InstitutePlan.stripe_price_id` /
`ModuleProduct.stripe_price_id`. Two guards keep that honest:

- `sync_stripe_prices` matches **USD prices only**, and refuses (`[AMBIGUOUS]`) an
  amount with more than one active USD price rather than taking whichever Stripe
  listed last — the old amount-only match silently collided across currencies.
- `assert_subscription_price_currency()` runs before every subscription Checkout
  Session, plan change and module add-on, and raises if the attached Price is not
  USD. Callers log it and show the user an error; nobody is charged.

So a package still pointing at a non-USD price **blocks checkout** rather than
charging the wrong currency. Fix it by pointing the record at a USD price
(`python manage.py sync_stripe_prices --dry-run`, then for real, or edit
`stripe_price_id` in the Django admin) — it is a stored DB column, so creating or
archiving prices in the Stripe dashboard alone changes nothing.

Existing subscriptions are not migrated by that: a Stripe subscription's currency
cannot be modified, so anyone already billing in the wrong currency has to be
cancelled and re-subscribed through a fresh checkout.

School invoices to parents are a separate flow and still bill in each school's own
`default_currency` — see `create_invoice_checkout_session`.

## Entitlement API

Other apps gate access via the entitlements module rather than reading Subscription/Module rows directly:

```python
from billing.entitlements import has_module_access, check_plan_limit
```

This is the integration surface for plan-aware features.

## "Subscribed students only" filters

Pages that offer a *subscribed students only* filter (Manage Students, the
progress-report preview) narrow their queryset through one shared definition
rather than restating the statuses:

```python
from billing.selectors import filter_subscribed

qs = filter_subscribed(qs, path='student__subscription')  # active or trialing
```

A student's **own** `Subscription` decides it. A school's `SchoolSubscription`
is deliberately not consulted: every student of a subscribed institute would
then match, and a filter that matches everybody says nothing.

## Dependencies

- **accounts** — `CustomUser` is the payer / subscriber.
- **classroom** — `School` and `Department` own the subscription scope.
- **audit** — billing events are recorded via `audit.services.log_event`.

## External services

- **Stripe** — Checkout sessions, subscriptions, webhooks, customer portal.
