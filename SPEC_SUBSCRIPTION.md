# Subscription, Billing, Enforcement & Security System

**Jira:** CPP-55
**Version:** 1.0
**Last Revised:** 2026-03-21

---

## Overview

A complete SaaS subscription system for Wizards Learning Hub covering institute plans, module add-ons, Stripe billing, feature gating, account blocking, audit logging, and risk detection.

---

## Pricing Model

### Individual Students
- **$19.90/month** with 14-day free trial
- Trial starts on first login; must subscribe after trial or login is blocked
- Managed via `Package` + `Subscription` models (pre-existing)

### Institute Plans

| Plan | Price | Classes | Students | Invoices/yr | Extra Invoice |
|------|-------|---------|----------|-------------|---------------|
| Basic | $89/mo | 5 | 100 | 500 | $0.30 |
| Silver | $129/mo | 10 | 200 | 750 | $0.25 |
| Gold | $159/mo | 15 | 300 | 1,000 | $0.20 |
| Platinum | $189/mo | 20 | 400 | 2,000 | $0.15 |

### Module Add-ons ($10/month each)
- **Teachers Attendance** — teacher self-attendance, session attendance marking
- **Students Attendance** — student attendance history, self-marking, approvals, reports
- **Student Progress Reports** — criteria management, progress recording, reports

---

## Architecture

### New Models

| Model | App | Purpose |
|-------|-----|---------|
| `InstitutePlan` | billing | Plan tiers with limits and pricing |
| `SchoolSubscription` | billing | Links School to plan with Stripe IDs and status |
| `ModuleSubscription` | billing | Per-school module add-ons |
| `StripeEvent` | billing | Webhook idempotency table |
| `AuditLog` | audit | Security event logging |

### Modified Models

| Model | Changes |
|-------|---------|
| `CustomUser` | Added: `is_blocked`, `blocked_at`, `blocked_reason`, `blocked_by`, `block_type`, `block_expires_at` |
| `School` | Added: `is_suspended`, `suspended_at`, `suspended_reason`, `suspended_by` |
| `Subscription` | Added: `cancelled_at`, `cancel_at_period_end` |

### Service Layer

| File | Purpose |
|------|---------|
| `billing/entitlements.py` | Plan limit checks, module access, multi-school logic |
| `billing/stripe_service.py` | Stripe API wrapper (customers, checkout, plans, modules, billing portal) |
| `billing/webhook_handlers.py` | Event-specific Stripe webhook handlers |
| `billing/mixins.py` | `PlanRequiredMixin`, `ModuleRequiredMixin` for view enforcement |
| `billing/rate_limiting.py` | Cache-based rate limiting utility |
| `audit/services.py` | `log_event()` audit logging helper |
| `audit/risk.py` | Risk detection functions (trial abuse, brute-force, payment failures) |

---

## Subscription Lifecycle

### States
```
trialing → active → (past_due → active) or cancelled
trialing → expired (trial ended without subscribing)
active → cancelled (user cancels)
any → suspended (admin action)
```

### Institute Registration Flow
1. User registers via `TeacherCenterRegisterView`
2. `School` created with user as admin
3. `SchoolSubscription` created with `status=trialing`, `trial_end=now+14days`
4. After trial: must subscribe via Stripe Checkout or access is blocked

### Stripe Checkout Flow
1. User selects plan on `/billing/institute/plans/`
2. `InstituteCheckoutView` creates Stripe Checkout Session
3. User completes payment on Stripe-hosted page
4. Stripe sends `checkout.session.completed` webhook
5. `handle_checkout_completed()` activates subscription
6. User redirected to success page

---

## Feature Gating

### Plan Limit Enforcement
- **Class creation**: `check_class_limit(school)` called in `CreateClassView` and `HoDCreateClassView`
- **Student addition**: `check_student_limit(school)` called in `SchoolStudentManageView` and `EnrollmentApproveView`
- **Invoice generation**: `record_invoice_usage()` called in `create_draft_invoices()`, overages billed via Stripe metered pricing

### Module Gating
20 views gated via `ModuleRequiredMixin`:

| Module | Gated Views |
|--------|------------|
| `teachers_attendance` | TeacherSelfAttendanceView |
| `students_attendance` | SessionAttendanceView, StudentAttendanceHistoryView, StudentSelfMarkAttendanceView, approval views, ClassAttendanceView, HoDAttendanceReportView, AttendanceDetailView |
| `student_progress_reports` | ProgressCriteriaListView, ProgressCriteriaCreateView, approval views, RecordProgressView, StudentProgressView, StudentProgressReportView |

Navigation links hidden via `{% school_has_module %}` template tag in sidebars.

### Multi-School Students
Students enrolled in multiple institutes use **ANY-school logic**:
- Module access: allowed if ANY school has the module
- Subscription check: not blocked if ANY school is active
- Plan limits: always per-school (school admin's responsibility)

---

## Security

### Account Blocking
- **User blocking**: temporary (with expiry) or permanent, with reason and admin tracking
- **School suspension**: suspends all users in the school
- `AccountBlockMiddleware` enforces on every request, force-logs-out blocked users
- Session invalidation deletes all DB sessions for the blocked user

### Rate Limiting
- Login: 5 attempts per 15 minutes per IP
- Resets on successful login
- Uses Django cache framework

### Audit Logging
Events logged with user, school, IP, user agent, endpoint, and structured detail:

| Event | Category | Trigger |
|-------|----------|---------|
| `login_success` | auth | Successful login |
| `login_failed` | auth | Failed login attempt |
| `login_rate_limited` | auth | Rate limit exceeded |
| `module_access_denied` | entitlement | Accessing gated feature without module |
| `subscription_expired_access` | entitlement | Accessing feature with expired subscription |
| `payment_succeeded` | billing | Stripe payment webhook |
| `payment_failed` | billing | Stripe payment failure webhook |
| `user_blocked` | admin_action | Admin blocks a user |
| `blocked_user_access_attempt` | auth | Blocked user tries to access system |
| `suspended_school_access_attempt` | auth | User from suspended school tries to access |

### Risk Detection
- `detect_trial_abuse()` — IPs registering multiple accounts
- `detect_rapid_login_failures()` — brute-force detection
- `detect_payment_failure_pattern()` — repeated payment failures
- `detect_module_abuse()` — repeated gated feature access attempts
- `get_risk_summary()` — dashboard-ready counts

---

## URLs

### Institute Billing
| URL | View | Method |
|-----|------|--------|
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

### Admin Actions
| URL | View | Method |
|-----|------|--------|
| `/admin-dashboard/block-user/` | BlockUserView | POST |
| `/admin-dashboard/unblock-user/` | UnblockUserView | POST |
| `/admin-dashboard/suspend-school/` | SuspendSchoolView | POST |
| `/admin-dashboard/unsuspend-school/` | UnsuspendSchoolView | POST |

---

## Management Commands

```bash
# Reset yearly invoice counters (schedule via cron on Jan 1)
python manage.py reset_invoice_counters
python manage.py reset_invoice_counters --dry-run
```

---

## Test Coverage

53 tests covering:
- Plan model seed data and limits
- SchoolSubscription states and properties
- Entitlement checks (class, student, invoice limits)
- Module access (enabled, disabled, multi-school)
- Multi-school ANY-logic for subscriptions and modules
- Rate limiting (within limit, exceeds, reset, independent keys)
- Account blocking (permanent, temporary auto-expire, school suspension)
- Registration creates subscription
- Module gating redirects
- Login audit logging (success/failure)
- Stripe event idempotency
- URL resolution for all new endpoints
- Risk summary queries
- Audit log creation and service behavior

Run tests: `python manage.py test billing audit`
