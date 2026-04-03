# Full System Specification — claude/gracious-ramanujan

**Generated:** 2026-03-23 (Updated: 2026-03-24)
**Branch:** claude/gracious-ramanujan
**Base:** main (cc6de993)

---

## 1. System Overview

A Django-based SaaS school management platform (Wizards Learning Hub) with:
- **Multi-tenant architecture**: Schools operate independently under one platform
- **Dual billing tracks**: Individual students ($19.90/mo) and Institute plans ($89-$189/mo)
- **Module add-ons**: Optional paid features ($10/mo each)
- **Stripe integration**: Checkout, subscriptions, webhooks, billing portal
- **Role-based access**: 11 roles with hierarchical permissions
- **Audit & security**: Event logging, rate limiting, risk detection, account blocking
- **Subdomain routing**: Subject apps served from subdomains (maths.*, coding.*, etc.)

---

## 2. Data Model

### 2.1 Accounts App

#### CustomUser (extends AbstractUser)
| Field | Type | Purpose |
|-------|------|---------|
| date_of_birth | DateField (nullable) | Student age tracking |
| country, region | CharField | Location |
| package | FK → Package (nullable) | Individual student's active package |
| roles | M2M → Role (through UserRole) | Multi-role support |
| phone, street_address, city, postal_code | CharField | Contact/address |
| must_change_password | BooleanField (default=False) | Forces password change on first login |
| profile_completed | BooleanField (default=True) | Profile completion gate |
| is_blocked | BooleanField | Account blocking flag |
| blocked_at, blocked_reason, blocked_by, block_type, block_expires_at | Various | Block metadata |

**Properties:** `primary_role`, `is_student`, `is_individual_student`, `is_any_teacher`, `is_head_of_institute`, `is_head_of_department`, `is_accountant`, `is_institute_owner`, `is_parent`, `age`

#### Role
Constants: `ADMIN`, `SENIOR_TEACHER`, `TEACHER`, `JUNIOR_TEACHER`, `STUDENT`, `INDIVIDUAL_STUDENT`, `ACCOUNTANT`, `HEAD_OF_INSTITUTE`, `HEAD_OF_DEPARTMENT`, `INSTITUTE_OWNER`, `PARENT`

#### UserRole (through table)
| Field | Type |
|-------|------|
| user | FK → CustomUser |
| role | FK → Role |
| assigned_at | DateTimeField (auto) |
| assigned_by | FK → CustomUser (nullable) |

### 2.2 Billing App

#### Package (Individual Student Plans)
| Field | Type | Purpose |
|-------|------|---------|
| name | CharField | Plan name |
| class_limit | PositiveIntegerField (default=1) | 0 = unlimited |
| price | DecimalField | Monthly price |
| stripe_price_id | CharField | Stripe Price ID |
| billing_type | CharField | 'recurring' or 'one_time' |
| trial_days | PositiveSmallIntegerField (default=14) | Trial period |
| is_active | BooleanField | Availability flag |
| order | PositiveIntegerField | Display order |

#### DiscountCode (Individual Students)
| Field | Type | Purpose |
|-------|------|---------|
| code | CharField (unique) | Discount code string |
| discount_percent | PositiveSmallIntegerField (default=100) | 100 = fully free |
| max_uses | PositiveIntegerField (nullable) | Usage cap |
| uses | PositiveIntegerField | Current usage count |
| is_active, expires_at | Various | Validity |

#### PromoCode (Class Access Expansion)
| Field | Type | Purpose |
|-------|------|---------|
| code | CharField (unique) | Promo code string |
| class_limit | PositiveIntegerField (default=0) | 0 = unlimited classes |
| max_uses, uses | PositiveIntegerField | Usage tracking |
| redeemed_by | M2M → CustomUser | Redemption tracking |
| is_active, expires_at | Various | Validity |

#### InstitutePlan
| Field | Type | Purpose |
|-------|------|---------|
| name, slug | CharField/SlugField | Identity |
| price | DecimalField | Monthly price |
| stripe_price_id | CharField | Stripe Price ID |
| class_limit | PositiveIntegerField | Max active classes |
| student_limit | PositiveIntegerField | Max active students |
| invoice_limit_yearly | PositiveIntegerField | Free invoices per year |
| extra_invoice_rate | DecimalField | Per-invoice overage cost |
| stripe_overage_price_id | CharField | Stripe metered price for overages |
| trial_days | PositiveSmallIntegerField (default=14) | Trial period |
| is_active, order | Various | Display/availability |

**Seeded Plans:**
| Plan | Price | Classes | Students | Invoices/yr | Extra Invoice |
|------|-------|---------|----------|-------------|---------------|
| Basic | $89/mo | 5 | 100 | 500 | $0.30 |
| Silver | $129/mo | 10 | 200 | 750 | $0.25 |
| Gold | $159/mo | 15 | 300 | 1,000 | $0.20 |
| Platinum | $189/mo | 20 | 400 | 2,000 | $0.15 |

#### InstituteDiscountCode
| Field | Type | Purpose |
|-------|------|---------|
| code | CharField (unique) | Discount code |
| discount_percent | PositiveSmallIntegerField (default=100) | % off |
| override_class_limit | PositiveIntegerField (nullable) | Override plan class limit |
| override_student_limit | PositiveIntegerField (nullable) | Override plan student limit |
| max_uses | PositiveIntegerField (default=1) | Single-use by default |
| uses | PositiveIntegerField | Current usage |
| stripe_coupon_id | CharField | Stripe Coupon for billing discount |
| is_active, expires_at | Various | Validity |

#### SchoolSubscription
| Field | Type | Purpose |
|-------|------|---------|
| school | OneToOne → School | One subscription per school |
| plan | FK → InstitutePlan (nullable) | Current plan |
| discount_code | FK → InstituteDiscountCode (nullable) | Applied discount |
| stripe_subscription_id | CharField | Stripe sub ID |
| stripe_customer_id | CharField | Stripe customer ID |
| status | CharField | trialing/active/past_due/cancelled/expired/suspended |
| trial_end | DateTimeField (nullable) | Trial expiry |
| current_period_start/end | DateTimeField (nullable) | Billing period |
| has_used_trial | BooleanField (default=False) | Prevents repeat trials |
| invoices_used_this_year | PositiveIntegerField | Invoice counter |
| invoice_year_start | DateField (nullable) | Year boundary |

**Properties:** `is_active_or_trialing`, `trial_days_remaining`

#### ModuleSubscription
| Field | Type | Purpose |
|-------|------|---------|
| school_subscription | FK → SchoolSubscription | Parent sub |
| module | CharField | Module slug (unique with school_subscription) |
| stripe_subscription_item_id | CharField | Stripe item ID |
| is_active | BooleanField | Active flag |
| activated_at, deactivated_at | DateTimeField | Lifecycle dates |

**Module Choices:** `teachers_attendance`, `students_attendance`, `student_progress_reports`

#### Subscription (Individual Students)
| Field | Type | Purpose |
|-------|------|---------|
| user | OneToOne → CustomUser | One sub per individual student |
| package | FK → Package (nullable) | Current package |
| stripe_subscription_id, stripe_customer_id | CharField | Stripe IDs |
| status | CharField | active/trialing/past_due/cancelled/expired |
| trial_end, current_period_start/end | DateTimeField | Timing |
| cancelled_at | DateTimeField (nullable) | When cancelled |
| cancel_at_period_end | BooleanField | Pending cancellation |

#### Payment
| Field | Type | Purpose |
|-------|------|---------|
| user | FK → CustomUser | Payer |
| package | FK → Package (nullable) | What was purchased |
| stripe_payment_intent_id, stripe_checkout_session_id | CharField | Stripe IDs |
| amount | DecimalField | Payment amount |
| currency | CharField (default='nzd') | Currency |
| status | CharField | pending/succeeded/failed/refunded |

#### StripeEvent
| Field | Type | Purpose |
|-------|------|---------|
| event_id | CharField (unique, indexed) | Stripe event ID |
| event_type | CharField | Event type string |
| processed_at | DateTimeField (auto) | When processed |
| payload | JSONField | Full event data |

### 2.3 Audit App

#### AuditLog
| Field | Type | Purpose |
|-------|------|---------|
| user | FK → CustomUser (nullable) | Who |
| school | FK → School (nullable) | School context |
| category | CharField | auth/billing/entitlement/admin_action/data_change |
| action | CharField (indexed) | Specific action string |
| result | CharField | allowed/blocked |
| detail | JSONField | Structured extra data |
| ip_address | GenericIPAddressField (nullable) | Client IP |
| user_agent | TextField | Browser/client info |
| endpoint | CharField | Request path |
| created_at | DateTimeField (auto, indexed) | Timestamp |

**Indexes:** (user, category), (school, category), (action, created_at), (category, result, created_at)

### 2.4 Classroom App (Modified)

#### School (new fields)
| Field | Type | Purpose |
|-------|------|---------|
| abn | CharField | Tax ID / ABN |
| street_address, city, state_region, postal_code, country | CharField | Structured address |
| is_suspended | BooleanField | Suspension flag |
| suspended_at | DateTimeField | When suspended |
| suspended_reason | TextField | Reason |
| suspended_by | FK → CustomUser | Who suspended |

---

## 3. Authentication & Authorization

### 3.1 Login
- **Backend:** `EmailOrUsernameBackend` — accepts either username or email
- **Rate Limiting:** 5 attempts per 15 minutes per IP (cache-based)
- **Audit Logging:** Every login attempt logged (success/failure/rate-limited)
- **Reset on success:** Rate limit counter cleared after successful login

### 3.2 Registration Flows

| Flow | View | Creates | Notes |
|------|------|---------|-------|
| Institute (HoI) | `TeacherCenterRegisterView` | User + School + SchoolSubscription | Multi-step: account → company/address → plan/discount |
| Individual Student | `IndividualStudentRegisterView` | User + Subscription | 3-step: account → personal/address → package/discount |
| School Student | `SchoolStudentRegisterView` | User (Student role) | Simple form, no subscription at registration |
| Parent | `ParentRegisterView` | User + ParentStudent link | Invite-based (UUID token) |
| Parent (existing user) | `ParentAcceptInviteView` | ParentStudent link | Adds PARENT role if needed |

### 3.3 Profile Completion Flow
- HoI creates students/teachers → `must_change_password=True`, `profile_completed=False`
- On first login, `ProfileCompletionMiddleware` redirects to `/accounts/complete-profile/`
- Student must: change password, fill profile, optionally enter discount code
- School students also need $19.90/mo subscription (redirected to Stripe Checkout)

### 3.4 Role Hierarchy (Priority Order)
1. admin → 2. institute_owner → 3. head_of_institute → 4. head_of_department → 5. accountant → 6. senior_teacher → 7. teacher → 8. junior_teacher → 9. individual_student → 10. student → 11. parent

---

## 4. Middleware Stack

| Middleware | Purpose | Placement |
|-----------|---------|-----------|
| `MathsRoomRedirectMiddleware` | 301 redirect from legacy domain | Before SubdomainURLRouting |
| `SubdomainURLRoutingMiddleware` | Routes subdomains to subject URL configs | Early |
| `AccountBlockMiddleware` | Blocks suspended/blocked users, force logout | After AuthenticationMiddleware |
| `ProfileCompletionMiddleware` | Forces password change + profile completion | After AccountBlock |
| `TrialExpiryMiddleware` | Auto-expires trials, redirects to upgrade | After ProfileCompletion |

### Allowed Paths (bypass middleware):
- **AccountBlock:** `/accounts/blocked/`, `/accounts/logout/`, `/admin/`
- **ProfileCompletion:** `/accounts/complete-profile/`, `/accounts/logout/`, `/accounts/blocked/`, `/admin/`, `/static/`
- **TrialExpiry:** `/accounts/trial-expired/`, `/accounts/logout/`, `/billing/`, `/stripe/`, `/admin/`

---

## 5. Billing & Stripe Integration

### 5.1 Stripe Service Layer (`stripe_service.py`)

| Function | Purpose |
|----------|---------|
| `get_or_create_customer(user=, school=)` | Creates/retrieves Stripe Customer |
| `create_institute_checkout_session()` | Creates Checkout Session for school plan |
| `create_individual_checkout_session()` | Creates Checkout Session for individual student |
| `create_student_checkout_session()` | Creates Checkout Session for school student ($19.90/mo) |
| `change_institute_plan()` | Modifies Stripe subscription to new plan (prorated) |
| `add_module_to_subscription()` | Adds $10/mo module as subscription item |
| `remove_module_from_subscription()` | Removes module subscription item (prorated) |
| `cancel_subscription()` | Cancels at period end or immediately |
| `report_invoice_overage()` | Reports metered usage for invoice overages |
| `create_billing_portal_session()` | Creates Stripe Billing Portal session |

### 5.2 Webhook Handling

**Endpoint:** `/stripe/webhook/` (CSRF exempt)
**Verification:** Stripe signature verification via `STRIPE_WEBHOOK_SECRET`
**Idempotency:** `StripeEvent` table prevents duplicate processing

| Event | Handler | Action |
|-------|---------|--------|
| `checkout.session.completed` | `handle_checkout_completed` | Activates subscription (institute or individual) |
| `customer.subscription.updated` | `handle_subscription_updated` | Syncs status, period dates, cancellation |
| `customer.subscription.deleted` | `handle_subscription_deleted` | Marks as cancelled |
| `invoice.payment_succeeded` | `handle_payment_succeeded` | Audit log only |
| `invoice.payment_failed` | `handle_payment_failed` | Audit log only |
| `payment_intent.succeeded` | Legacy handler | Backward compat for old PaymentIntent flow |

### 5.3 Checkout Session Flow Variants

**Institute:** Register → Select Plan → Stripe Checkout (with trial) → Webhook activates → Dashboard
**Individual Student:** Register → Select Package → Stripe Checkout → Webhook activates → Select Classes
**School Student:** HoI creates → First login → Complete Profile → Stripe Checkout ($19.90/mo) → Dashboard

---

## 6. Entitlements & Feature Gating

### 6.1 Plan Limit Checks (`entitlements.py`)
| Check | Function | Where Enforced |
|-------|----------|----------------|
| Class creation | `check_class_limit(school)` | `CreateClassView`, `HoDCreateClassView` |
| Student addition | `check_student_limit(school)` | `SchoolStudentManageView`, `EnrollmentApproveView` |
| Invoice generation | `check_invoice_limit(school)` | `create_draft_invoices()` |
| Invoice usage recording | `record_invoice_usage(school, count)` | After invoice generation |

### 6.2 Module Gating (`ModuleRequiredMixin`)

**teachers_attendance module (7 views):**
- TeacherSelfAttendanceView
- SessionAttendanceView
- StudentAttendanceApprovalListView
- StudentAttendanceApproveView
- StudentAttendanceRejectView
- StudentAttendanceBulkApproveView

**students_attendance module (4 views):**
- StudentAttendanceHistoryView
- StudentSelfMarkAttendanceView
- ClassAttendanceView
- HoDAttendanceReportView
- AttendanceDetailView

**student_progress_reports module (8 views):**
- ProgressCriteriaListView
- ProgressCriteriaCreateView
- ProgressCriteriaSubmitView
- ProgressCriteriaApprovalListView
- ProgressCriteriaApproveView
- ProgressCriteriaRejectView
- RecordProgressView
- StudentProgressView
- StudentProgressReportView

### 6.3 Multi-School Logic
- **Module access:** ANY-school — if student is in School A (has module) and School B (doesn't), access allowed
- **Subscription check:** ANY-school — not blocked if any school has active sub
- **Plan limits:** PER-school — each school's limits checked independently
- **Individual students:** Own `Subscription` object, independent of school subs

### 6.4 Template Tag
`{% raw %}{% school_has_module "module_slug" %}{% endraw %}` — hides sidebar navigation links for unsubscribed modules

---

## 7. Security

### 7.1 Account Blocking
| Action | Who Can Do It | What Happens |
|--------|--------------|--------------|
| Block user (temporary) | Admin, InstituteOwner, HoI | User blocked with expiry, auto-unblock when expired |
| Block user (permanent) | Admin, InstituteOwner, HoI | User permanently blocked |
| Unblock user | Admin, InstituteOwner, HoI | Block cleared |
| Suspend school | Admin only | All school users logged out, sessions deleted |
| Unsuspend school | Admin only | School access restored |

**Protections:**
- Cannot block yourself
- Non-admins cannot block admins
- Session invalidation on block (DB sessions deleted)

### 7.2 Risk Detection (`audit/risk.py`)
| Function | Detects | Thresholds |
|----------|---------|-----------|
| `detect_trial_abuse()` | IPs with multiple account registrations | 3+ accounts from same IP in 30 days |
| `detect_rapid_login_failures()` | Brute-force attempts | 5+ failures in 15 minutes |
| `detect_payment_failure_pattern()` | Repeated payment failures | 3+ failures in 30 days |
| `detect_module_abuse()` | Repeated gated feature access | 20+ denials in 60 minutes |
| `get_risk_summary()` | Dashboard overview | 24h/7d aggregates |

---

## 8. URL Map

### Accounts
| URL | View | Method |
|-----|------|--------|
| `/accounts/login/` | AuditLoginView | GET/POST |
| `/accounts/logout/` | LogoutView (CSRF exempt) | GET/POST |
| `/accounts/password_reset/` | DiagnosticPasswordResetView | GET/POST |
| `/accounts/signup/teacher/` | TeacherSignupView (redirect) | GET/POST |
| `/accounts/register/teacher-center/` | TeacherCenterRegisterView | GET/POST |
| `/accounts/register/individual-student/` | IndividualStudentRegisterView | GET/POST |
| `/accounts/register/school-student/` | SchoolStudentRegisterView | GET/POST |
| `/accounts/register/parent/<uuid:token>/` | ParentRegisterView | GET/POST |
| `/accounts/accept-invite/<uuid:token>/` | ParentAcceptInviteView | GET/POST |
| `/accounts/profile/` | ProfileView | GET/POST |
| `/accounts/complete-profile/` | CompleteProfileView | GET/POST |
| `/accounts/select-classes/` | SelectClassesView | GET/POST |
| `/accounts/account/change-package/` | ChangePackageView | GET |
| `/accounts/api/check-username/` | CheckUsernameView | GET (AJAX) |
| `/accounts/trial-expired/` | TrialExpiredView | GET |
| `/accounts/blocked/` | AccountBlockedView | GET |

### Billing
| URL | View | Method |
|-----|------|--------|
| `/billing/checkout/<int:package_id>/` | CheckoutView | GET |
| `/billing/create-payment-intent/<int:package_id>/` | CreatePaymentIntentView | POST |
| `/billing/confirm-payment/` | ConfirmPaymentView | POST |
| `/billing/success/` | CheckoutSuccessView | GET |
| `/billing/cancel/` | CheckoutCancelView | GET |
| `/stripe/webhook/` | StripeWebhookView | POST |
| `/billing/institute/plans/` | InstitutePlanSelectView | GET |
| `/billing/institute/checkout/` | InstituteCheckoutView | POST |
| `/billing/institute/checkout/success/` | InstituteCheckoutSuccessView | GET |
| `/billing/institute/change-plan/` | InstituteChangePlanView | POST |
| `/billing/institute/cancel/` | InstituteCancelSubscriptionView | POST |
| `/billing/institute/dashboard/` | InstituteSubscriptionDashboardView | GET |
| `/billing/institute/trial-expired/` | InstituteTrialExpiredView | GET |
| `/billing/institute/upgrade/` | InstitutePlanUpgradeView | GET |
| `/billing/portal/` | StripeBillingPortalView | GET |
| `/billing/module-required/` | ModuleRequiredView | GET |
| `/billing/institute/module/toggle/` | ModuleToggleView | POST |
| `/billing/history/` | BillingHistoryView | GET |

### Admin Actions
| URL | View | Method |
|-----|------|--------|
| `/admin-dashboard/block-user/` | BlockUserView | POST |
| `/admin-dashboard/unblock-user/` | UnblockUserView | POST |
| `/admin-dashboard/suspend-school/` | SuspendSchoolView | POST |
| `/admin-dashboard/unsuspend-school/` | UnsuspendSchoolView | POST |

---

## 9. Management Commands

| Command | Purpose |
|---------|---------|
| `reset_invoice_counters` | Resets yearly invoice counters (cron: Jan 1). Supports `--dry-run` |
| `sync_stripe_prices` | Fetches Stripe products/prices and syncs IDs into InstitutePlan, Package, and ModuleProduct records. Supports `--dry-run` |
| `backfill_subscriptions` | Creates SchoolSubscription records for schools created before billing system. Supports `--dry-run` and `--status` |
| `send_trial_expiry_warnings` | Sends email warnings to schools with expiring trials |

---

## 10. MISSING / UNCLEAR Components (Deep Analysis)

### 10.1 CRITICAL GAPS

#### A. No `PlanRequiredMixin` Usage Found
`PlanRequiredMixin` is defined in `billing/mixins.py` but **not applied to any view**. The spec says plan limits are checked, but only `ModuleRequiredMixin` is used. Class creation and student addition views do call `check_class_limit()` and `check_student_limit()` directly, but there is no view-level subscription-active check via `PlanRequiredMixin`. The `TrialExpiryMiddleware` partially covers this, but only for trial expiry — a cancelled/past_due subscription is not caught by middleware.

**Impact:** A school with a `cancelled` subscription (not expired trial) could still access all features.

#### B. ~~`school_student` Checkout Type Not Handled in Webhooks~~ **RESOLVED**
`handle_checkout_completed()` now handles `'school_student'` type alongside `'individual'`.

#### C. Invoice Year Reset Logic Incomplete
`SchoolSubscription.invoice_year_start` field exists but is **never set** during registration or subscription activation. `reset_invoice_counters` command resets `invoices_used_this_year` but doesn't set `invoice_year_start`. The `check_invoice_limit()` function doesn't verify whether the current year matches `invoice_year_start`.

**Impact:** Invoice counters may never reset properly; overages could accumulate forever or reset incorrectly.

#### D. InstituteDiscountCode `override_class_limit` and `override_student_limit` Never Used
These fields exist on the model but are **never read** by any entitlement check, view, or service. When a discount code with overrides is applied, the plan's default limits still apply.

**Impact:** Discount codes promising custom limits will not deliver on that promise.

#### E. ~~No Stripe Price IDs in Seed Data~~ **RESOLVED**
Added `sync_stripe_prices` management command that fetches Stripe products/prices and matches them to InstitutePlan, Package, and ModuleProduct records by price amount. Run after deployment to populate all Stripe IDs.

### 10.2 SIGNIFICANT GAPS

#### F. `DiscountCode` vs `InstituteDiscountCode` — Confusion
Two separate discount code systems exist:
- `DiscountCode` — used by individual students in `IndividualStudentRegisterView`
- `InstituteDiscountCode` — used by institutes AND school students in `CompleteProfileView`

The `DiscountCode` model has **no `stripe_coupon_id` field**, so individual student discounts that are not 100% free cannot apply Stripe-level discounts. The code does `getattr(discount, 'stripe_coupon_id', None)` which will always return `None`.

#### G. Subscription Status `suspended` Exists but Cannot Be Set
`SchoolSubscription.STATUS_SUSPENDED = 'suspended'` is defined but there is **no code path** that sets a subscription to this status. School suspension (`SuspendSchoolView`) sets `school.is_suspended = True` but does not change the subscription status.

**Impact:** The `suspended` status is dead code. Unclear if it should be set when a school is suspended.

#### H. `cancel_at_period_end` Not Synced for Institutes
`_sync_individual_subscription()` sets `sub.cancel_at_period_end = cancel_at_period_end`, but `_sync_institute_subscription()` does **not** track this field. `SchoolSubscription` model doesn't even have a `cancel_at_period_end` field.

**Impact:** Institute subscriptions pending cancellation at period end cannot be displayed correctly.

#### I. ~~No Module Add/Remove Views~~ **RESOLVED**
Added `ModuleToggleView` at `/billing/institute/module/toggle/` with Add/Remove buttons on the subscription dashboard. Module pricing stored in `ModuleProduct` model (database, not `.env`). Sidebar now includes Billing link for HoI/admin roles.

#### J. Individual Student Legacy PaymentIntent Flow
`CheckoutView`, `CreatePaymentIntentView`, and `ConfirmPaymentView` implement a legacy PaymentIntent-based checkout (not Checkout Sessions). This runs alongside the newer `create_individual_checkout_session()` flow. Both can create `Subscription` records.

**Impact:** Two parallel billing flows for individual students. Unclear which is canonical. Risk of duplicate subscriptions.

#### K. `has_used_trial` Not Checked on Upgrade/Downgrade
`SchoolSubscription.has_used_trial` exists to prevent repeat trials, but `InstituteCheckoutView` and `change_institute_plan()` do **not check this field**. A school could potentially downgrade and get a new trial.

**Impact:** Potential trial abuse on plan changes.

### 10.3 MINOR GAPS & UNCLEAR AREAS

#### L. `Package.billing_type` ('recurring' vs 'one_time') Never Used
The field exists but no logic branches on it. All packages are treated as recurring subscriptions.

#### M. No Email Notifications for Subscription Events
Payment succeeded/failed webhooks only log audit events. No email notifications sent to users for:
- Trial expiring soon
- Payment failed
- Subscription cancelled
- Trial expired

#### N. `Payment` Model Only Used in Legacy Flow
`Payment` records are only created in `ConfirmPaymentView` (legacy PaymentIntent flow). The newer Checkout Session flow does not create `Payment` records — only updates `Subscription` status.

#### O. No Billing History / Invoice List View
Users cannot see their past payments, current invoice, or upcoming charges. Only the subscription dashboard exists.

#### P. Context Processor Scope Unknown
`accounts/context_processors.py` exists but was not read. May provide subscription-related context to all templates — needs verification.

#### Q. `_SchoolResolverMixin` Session-Based School Selection
The mixin tries `request.session.get('current_school_id')` but **no code sets this session variable**. Multi-school users have no way to switch their "current school".

#### R. Rate Limiting Applies Only to Login
`check_rate_limit()` is only used in `AuditLoginView`. No rate limiting on:
- Registration endpoints
- Password reset
- API endpoints (`check-username`)
- Stripe checkout creation

#### S. No CSRF on Stripe Webhook But No Rate Limiting Either
The webhook endpoint is CSRF exempt (correct) but has no rate limiting or IP allowlisting.

#### T. `audit/views.py` is Empty
The audit app has `views.py` with only `from django.shortcuts import render`. No admin dashboard views for viewing audit logs or risk reports.

#### U. Template Tags `billing_tags.py` Not Analyzed
The `{% raw %}{% school_has_module %}{% endraw %}` template tag exists but its exact implementation wasn't included in the spec.

#### V. Welcome Email Sends Username in Plaintext
`emails/welcome_staff.html` and `.txt` templates appear to send the username (and possibly temporary password) via email.

#### W. ~~No Webhook Retry Handling~~ **RESOLVED**
Webhook view now returns 500 on handler failure (instead of recording the event and returning 200). Stripe will retry failed events. Also added `customer.subscription.created` handler and auto-creates `SchoolSubscription` for schools that existed before the billing system.

#### X. `Subscription` and `SchoolSubscription` Are Parallel Systems
Individual students use `Subscription` (per-user), institutes use `SchoolSubscription` (per-school). These share no base class or common interface, leading to duplicated logic in middleware, webhook handlers, and entitlements.

---

## 11. Test Coverage Summary

| Test File | Focus | Count |
|-----------|-------|-------|
| `billing/tests.py` | Plan limits, entitlements, module access, rate limiting, blocking | ~53 |
| `billing/tests_stripe.py` | Stripe webhook handlers, checkout flows | ~37 |
| `billing/tests_views_coverage.py` | Billing views, mixins, audit risk detection | 68 |
| `billing/tests_webhook_handlers.py` | Webhook handlers end-to-end, idempotency, auto-create subscriptions | 32 |
| `accounts/tests.py` | Registration, login, profile completion | ~varies |
| `classroom/tests/test_e2e_school_setup.py` | End-to-end school setup | ~varies |
| `classroom/tests/test_e2e_invoicing.py` | End-to-end invoicing | ~varies |
| `classroom/tests/test_e2e_attendance_progress.py` | E2E attendance and progress | ~varies |
| `classroom/tests/test_registration_flows.py` | All registration paths | ~varies |
| `classroom/tests/test_student_flow.py` | Student lifecycle | ~varies |
| `classroom/tests/test_views_coverage.py` | Classroom views (home, class CRUD, HoD, admin, contact) | 102 |
| `classroom/tests/test_remaining_views_coverage.py` | Teacher, student, department, email, salary, invoicing, progress views | 121 |
| `classroom/tests/test_department_views_coverage.py` | Department CRUD, HoD assignment, subjects, levels | 56 |
| `classroom/tests/test_invoicing_main_views_coverage.py` | Invoicing views, fee config, accounting, role access | 85 |
| `classroom/tests/test_accounts_admin_teacher_coverage.py` | Profile, select classes, parent invite, admin, teacher views | 52 |
| `classroom/tests/test_sidebar_navigation.py` | Sidebar links presence for all roles (billing link regression) | 47 |
| `classroom/tests/test_hod_cross_department.py` | HoD cross-department class visibility and filtering | 11 |

**Total:** 1,000+ passing tests at 80% code coverage

## 12. New Models Added

### ModuleProduct
| Field | Type | Purpose |
|-------|------|---------|
| module | CharField(50, unique) | Module slug (e.g. `students_attendance`) |
| name | CharField(100) | Display name |
| stripe_price_id | CharField(200, blank) | Stripe Price ID (synced via `sync_stripe_prices`) |
| price | DecimalField | Monthly price (default $10) |
| is_active | BooleanField | Toggle availability |

Replaces the `MODULE_STRIPE_PRICES` settings dict — all module pricing now stored in database.

## 13. HoD Cross-Department Access Pattern

HoD users who teach classes outside their headed department follow this access pattern:
- **Headed department**: Full access to all classes, students, attendance
- **Other departments**: Access only to classes they personally teach

Views updated with `Q(department__head=user) | Q(teachers=user)` pattern:
- `ClassDetailView`, `EditClassView`, `AssignStudentsView`
- `ClassAttendanceView`, `UpdateStudentFeeView`, `ClassStudentRemoveView`
- `HoDManageClassesView` (with department dropdown filter)
- `HoDOverviewView` (dashboard stats include all teaching classes)
- `HoDAttendanceReportView` (attendance data includes all teaching classes)

## 14. Sidebar Navigation

Billing link added to:
- `sidebar_admin.html` (Admin/HoI/Institute Owner)
- `sidebar_hod.html` (Head of Department)

Links to `institute_subscription_dashboard` for plan management and module toggles.

---

## 12. Configuration

### Settings Required
| Setting | Purpose |
|---------|---------|
| `STRIPE_SECRET_KEY` | Stripe API key |
| `STRIPE_PUBLISHABLE_KEY` | Stripe frontend key |
| `STRIPE_WEBHOOK_SECRET` | Webhook signature verification |
| `STRIPE_CURRENCY` | Default currency (nzd) |
| `AUTHENTICATION_BACKENDS` | Must include `accounts.backends.EmailOrUsernameBackend` |

### Deployment Checklist
1. `python manage.py migrate` — apply all migrations including `ModuleProduct`
2. `python manage.py sync_stripe_prices` — sync Stripe Price IDs into database
3. `python manage.py backfill_subscriptions` — create subscriptions for legacy schools
4. Configure Stripe webhook endpoint with events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`

### Subdomain Configuration
| Subdomain | URL Config |
|-----------|-----------|
| maths.* | `cwa_classroom.urls_maths` |
| coding.* | `cwa_classroom.urls_coding` |
| music.* | `cwa_classroom.urls_music` |
| science.* | `cwa_classroom.urls_science` |
| (default) | `ROOT_URLCONF` |
